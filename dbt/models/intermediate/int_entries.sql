-- Uma linha por entrada que já teve versão jogável: domínio, quando entrou, quando saiu da lista,
-- quando foi conferida pela primeira vez e em que situação estava nessa primeira conferência.
-- O domínio é o atual; para quem saiu da lista ou perdeu o endereço, o último conhecido.
with

first_snapshot as (
    select source, min(run_at) as baseline_at
    from {{ ref('stg_catalog_runs') }}
    where status = 'ok'
    group by source
),

removed as (
    select source, key, max(seen_at) as removed_at, any_value(title) as title, any_value(entry_play_host) as play_host
    from {{ ref('stg_catalog_changes') }}
    where change = 'removed'
    group by source, key
),

lost_host as (
    select source, key, arg_max(old_play_host, seen_at) as play_host
    from {{ ref('stg_catalog_changes') }}
    where change = 'changed' and play_host_changed and old_play_host is not null
    group by source, key
),

entries as (
    select e.source, e.key, e.title, coalesce(e.play_host, l.play_host) as play_host, null::timestamp as removed_at
    from {{ ref('stg_entries') }} e
    left join lost_host l using (source, key)
    union all
    select r.source, r.key, r.title, r.play_host, r.removed_at
    from removed r
    anti join {{ ref('stg_entries') }} e using (source, key)
),

-- Desde quando a entrada tem versão jogável: quando entrou na lista, ou quando ganhou um domínio depois.
playable_since as (
    select
        e.source,
        e.key,
        greatest(
            coalesce(max(c.seen_at) filter (where c.change = 'added'), f.baseline_at),
            coalesce(max(c.seen_at) filter (where c.change = 'changed' and c.play_host_changed and c.new_play_host is not null), f.baseline_at)
        ) as playable_since
    from entries e
    join first_snapshot f using (source)
    left join {{ ref('stg_catalog_changes') }} c using (source, key)
    group by e.source, e.key, f.baseline_at
),

first_check as (
    select p.source, p.key, min(r.run_at) as first_check_at
    from playable_since p
    join {{ ref('stg_status_runs') }} r on r.source = p.source and r.run_at >= p.playable_since
    group by p.source, p.key
),

first_change as (
    select source, key, arg_min(from_state, changed_at) as from_state
    from {{ ref('stg_status_changes') }}
    group by source, key
)

select
    e.source,
    e.key,
    e.title,
    e.play_host,
    e.removed_at,
    fc.first_check_at,
    coalesce(ch.from_state, s.state) as first_state
from entries e
join first_check fc using (source, key)
left join first_change ch using (source, key)
left join {{ ref('stg_status_current') }} s using (source, key)
where e.play_host is not null
  and coalesce(ch.from_state, s.state) is not null

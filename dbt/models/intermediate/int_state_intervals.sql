-- A história de cada entrada em intervalos: de quando a situação começou até quando mudou.
-- O fim fica nulo enquanto a situação dura. A troca para 'unlisted' (a entrada deixou de ter
-- versão jogável listada) encerra o último intervalo e não vira intervalo.
with

starts as (
    select source, key, first_check_at as started_at, first_state as state, true as is_first
    from {{ ref('int_entries') }}
    union all
    select c.source, c.key, c.changed_at, c.to_state, false
    from {{ ref('stg_status_changes') }} c
    join {{ ref('int_entries') }} e using (source, key)
),

ordered as (
    select
        *,
        lead(started_at) over w as next_at,
        lead(state) over w as next_state
    from starts
    window w as (partition by source, key order by started_at)
)

select
    o.source,
    o.key,
    e.title,
    e.play_host,
    o.state,
    o.started_at,
    o.is_first,
    coalesce(o.next_at, e.removed_at) as ended_at,
    case
        when o.next_state = 'unlisted' then 'removed'
        when o.next_state is not null then 'changed'
        when e.removed_at is not null then 'removed'
    end as end_reason
from ordered o
join {{ ref('int_entries') }} e using (source, key)
where o.state <> 'unlisted'

-- A situação de todas as versões listadas em cada conferência, refeita a partir das trocas.
-- Separa as que estavam fora do ar por queda coletiva das que caíram sozinhas.
select
    r.source,
    r.run_at,
    count(*) as checked,
    count(*) filter (where i.state = 'online') as online,
    count(*) filter (where i.state = 'unstable') as unstable,
    count(*) filter (where i.state = 'offline') as offline,
    count(*) filter (where i.state = 'unverified') as unverified,
    count(*) filter (where i.state = 'offline' and o.collective) as offline_collective,
    count(*) filter (where i.state = 'offline' and not coalesce(o.collective, false)) as offline_isolated
from {{ ref('stg_status_runs') }} r
join {{ ref('int_state_intervals') }} i
  on i.source = r.source
 and i.started_at <= r.run_at
 and (i.ended_at is null or i.ended_at > r.run_at)
left join {{ ref('gold_outages') }} o
  on o.source = i.source and o.key = i.key and o.started_at = i.started_at
group by r.source, r.run_at

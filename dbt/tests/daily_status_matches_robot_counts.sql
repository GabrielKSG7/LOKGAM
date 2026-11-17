-- A situação refeita a partir das trocas precisa bater com o que o robô contou em cada conferência.
-- Se não bater, a reconstrução da história (ou a gravação das trocas) tem um defeito.
select r.source, r.run_at, r.targets, d.checked, r.online, d.online, r.offline, d.offline
from {{ ref('stg_status_runs') }} r
left join {{ ref('gold_daily_status') }} d using (source, run_at)
where d.checked is distinct from r.targets
   or d.online is distinct from r.online
   or d.unstable is distinct from r.unstable
   or d.offline is distinct from r.offline
   or d.unverified is distinct from r.unverified

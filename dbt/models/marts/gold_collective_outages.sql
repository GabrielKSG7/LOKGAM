-- Quedas coletivas: um domínio derrubando várias versões na mesma conferência.
select
    source,
    play_host,
    started_at,
    any_value(started_basis) as started_basis,
    count(*) as ports,
    count(*) filter (where ended_at is null) as still_down,
    count(*) filter (where end_reason = 'recovered') as recovered,
    max(ended_at) filter (where end_reason = 'recovered') as last_recovered_at
from {{ ref('gold_outages') }}
where collective
group by source, play_host, started_at

-- Os números de cabeçalho, uma linha por fonte de ports.
with

span as (
    select source, min(run_at) as first_check_at, max(run_at) as last_check_at, count(*) as checks
    from {{ ref('stg_status_runs') }}
    group by source
),

latest as (
    select * from {{ ref('gold_daily_status') }}
    qualify row_number() over (partition by source order by run_at desc) = 1
),

outages as (
    select
        source,
        count(*) filter (where started_basis = 'observed') as observed_outages,
        count(*) filter (where started_basis = 'observed' and collective) as observed_collective,
        count(*) filter (where started_basis = 'observed' and end_reason = 'recovered') as observed_recovered,
        median(hours_down) filter (where started_basis = 'observed' and end_reason = 'recovered') as median_hours_down,
        count(*) filter (where started_basis = 'before_first_check' and ended_at is null) as down_since_first_check,
        count(*) filter (where started_basis = 'before_first_check' and end_reason = 'recovered') as came_back_after_first_check
    from {{ ref('gold_outages') }}
    group by source
),

catalog as (
    select
        source,
        sum(added) filter (where not baseline) as added_since_baseline,
        sum(removed) filter (where not baseline) as removed_since_baseline,
        min(run_at) as catalog_first_at,
        max(run_at) as catalog_last_at
    from {{ ref('stg_catalog_runs') }}
    group by source
)

select
    s.source,
    s.first_check_at,
    s.last_check_at,
    s.checks,
    round(date_diff('hour', s.first_check_at, s.last_check_at) / 24.0, 1) as days_observed,
    l.checked as checked_now,
    l.online as online_now,
    l.offline as offline_now,
    coalesce(o.observed_outages, 0) as observed_outages,
    coalesce(o.observed_collective, 0) as observed_collective,
    coalesce(o.observed_recovered, 0) as observed_recovered,
    o.median_hours_down,
    coalesce(o.down_since_first_check, 0) as down_since_first_check,
    coalesce(o.came_back_after_first_check, 0) as came_back_after_first_check,
    (select count(*) from {{ ref('gold_collective_outages') }} c where c.source = s.source and c.started_basis = 'observed') as collective_events,
    coalesce(c.added_since_baseline, 0) as added_since_baseline,
    coalesce(c.removed_since_baseline, 0) as removed_since_baseline,
    round(coalesce(c.added_since_baseline, 0) / nullif(date_diff('hour', c.catalog_first_at, c.catalog_last_at) / 24.0, 0), 1) as added_per_day
from span s
join latest l using (source)
left join outages o using (source)
left join catalog c using (source)

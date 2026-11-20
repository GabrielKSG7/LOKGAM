-- A base dia a dia: quantos ports estavam listados, quantos entraram e saíram, e quantas
-- versões estavam fora do ar. Um dia é representado pela última coleta dele.
with

days as (
    select cast(run_at as date) as day, max(run_at) as run_at
    from {{ ref('stg_catalog_runs') }}
    group by 1
),

listed as (
    select
        d.day,
        count(*) filter (where p.first_seen <= d.run_at and (p.removed_at is null or p.removed_at > d.run_at)) as ports,
        count(*) filter (where p.is_console and p.first_seen <= d.run_at and (p.removed_at is null or p.removed_at > d.run_at)) as console_ports,
        count(*) filter (where p.first_seen_basis = 'added' and cast(p.first_seen as date) = d.day) as added,
        count(*) filter (where p.first_seen_basis = 'added' and p.is_console and cast(p.first_seen as date) = d.day) as added_console,
        count(*) filter (where cast(p.removed_at as date) = d.day) as removed
    from days d
    cross join {{ ref('int_ports') }} p
    group by d.day
),

status as (
    select cast(run_at as date) as day, arg_max(offline, run_at) as offline, arg_max(checked, run_at) as checked
    from {{ ref('gold_daily_status') }}
    group by 1
)

select l.day, d.run_at, l.ports, l.console_ports, l.added, l.added_console, l.removed, s.checked, s.offline
from listed l
join days d using (day)
left join status s using (day)

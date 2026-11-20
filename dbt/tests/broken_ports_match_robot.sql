-- As versões fora do ar agora são as que o robô contou como fora na última conferência.
with last_run as (select offline from {{ ref('stg_status_runs') }} order by run_at desc limit 1)
select * from last_run where offline <> (select count(*) from {{ ref('gold_broken_ports') }})

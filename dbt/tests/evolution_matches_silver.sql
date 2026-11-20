-- O último dia da evolução e o resumo por plataforma contam os mesmos ports listados que a prata.
with silver as (select count(*) as n from {{ ref('stg_silver_ports') }} where listed),
last_day as (select ports from {{ ref('gold_evolution_daily') }} order by day desc limit 1),
platforms as (select sum(ports) as n from {{ ref('gold_platform_summary') }})
select * from silver, last_day, platforms
where silver.n <> last_day.ports or silver.n <> platforms.n

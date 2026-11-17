-- O ritmo de cada catálogo: entradas e mudanças por coleta que trouxe retrato novo.
select
    source,
    run_at,
    entries,
    added,
    removed,
    changed,
    baseline
from {{ ref('stg_catalog_runs') }}
where status = 'ok'

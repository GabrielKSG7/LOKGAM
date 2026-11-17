-- Uma linha por coleta bem-sucedida de cada fonte (retrato novo ou original sem mudança).
select
    source,
    cast(run_at as timestamp) as run_at,
    status,
    rows as entries,
    added,
    removed,
    changed,
    baseline
from {{ read_jsonl('bronze/runs.jsonl', {
    'run_at': 'VARCHAR', 'source': 'VARCHAR', 'status': 'VARCHAR', 'rows': 'INTEGER',
    'added': 'INTEGER', 'removed': 'INTEGER', 'changed': 'INTEGER', 'baseline': 'BOOLEAN'}) }}
where status in ('ok', 'unchanged')

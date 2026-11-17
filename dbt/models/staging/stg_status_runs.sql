-- Uma linha por conferência diária que gravou situações.
select
    source,
    cast(run_at as timestamp) as run_at,
    targets,
    online,
    unstable,
    offline,
    unverified,
    transitions
from {{ read_jsonl('bronze/status_runs.jsonl', {
    'run_at': 'VARCHAR', 'source': 'VARCHAR', 'status': 'VARCHAR', 'targets': 'INTEGER', 'online': 'INTEGER',
    'unstable': 'INTEGER', 'offline': 'INTEGER', 'unverified': 'INTEGER', 'transitions': 'INTEGER'}) }}
where status = 'ok'

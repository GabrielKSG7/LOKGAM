-- Cada troca de situação vista pela conferência diária.
select
    source,
    key,
    cast("at" as timestamp) as changed_at,
    "from" as from_state,
    "to" as to_state,
    reason,
    http_status
from {{ read_jsonl('bronze/*/status_changes.jsonl', {
    'source': 'VARCHAR', 'at': 'VARCHAR', 'key': 'VARCHAR', 'from': 'VARCHAR', 'to': 'VARCHAR',
    'reason': 'VARCHAR', 'http_status': 'INTEGER'}) }}

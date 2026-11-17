-- O que entrou, saiu ou mudou em cada fonte. Da entrada que saiu ficam o título e o domínio.
select
    source,
    cast(seen_at as timestamp) as seen_at,
    change,
    key,
    title,
    json_extract_string(entry, '$.play_host') as entry_play_host,
    json_exists(fields, '$.play_host') as play_host_changed,
    json_extract_string(fields, '$.play_host[0]') as old_play_host,
    json_extract_string(fields, '$.play_host[1]') as new_play_host
from {{ read_jsonl('bronze/*/changes.jsonl', {
    'seen_at': 'VARCHAR', 'source': 'VARCHAR', 'change': 'VARCHAR', 'key': 'VARCHAR', 'title': 'VARCHAR',
    'entry': 'JSON', 'fields': 'JSON'}) }}

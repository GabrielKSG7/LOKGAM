-- Entradas do retrato atual de cada fonte.
select
    {{ source_from_filename() }} as source,
    key,
    title,
    play_host
from {{ read_jsonl('bronze/*/snapshot.jsonl', {'key': 'VARCHAR', 'title': 'VARCHAR', 'play_host': 'VARCHAR'}, with_source=true) }}

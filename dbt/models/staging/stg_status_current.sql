-- A situação atual de cada entrada conferida e desde quando.
select
    {{ source_from_filename() }} as source,
    key,
    state,
    cast(since as timestamp) as since
from {{ read_jsonl('bronze/*/status.jsonl', {'key': 'VARCHAR', 'state': 'VARCHAR', 'since': 'VARCHAR'}, with_source=true) }}

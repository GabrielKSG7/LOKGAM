select source, key, count(*) from {{ ref('int_entries') }} group by all having count(*) > 1

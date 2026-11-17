-- Uma entrada está em uma situação só de cada vez.
select a.source, a.key, a.started_at, b.started_at
from {{ ref('int_state_intervals') }} a
join {{ ref('int_state_intervals') }} b
  on a.source = b.source and a.key = b.key and a.started_at < b.started_at
 and (a.ended_at is null or a.ended_at > b.started_at)

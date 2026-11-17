-- Cada período fora do ar de uma versão listada.
-- started_basis: 'observed' se a conferência viu a queda; 'before_first_check' se já estava fora
-- na primeira conferência, e aí o começo real é desconhecido.
-- Uma queda é coletiva quando ao menos {{ var('collective_min_ports') }} versões do mesmo domínio caem na mesma conferência.
with

offline as (
    select
        source,
        key,
        title,
        play_host,
        started_at,
        case when is_first then 'before_first_check' else 'observed' end as started_basis,
        ended_at,
        case end_reason when 'changed' then 'recovered' else end_reason end as end_reason
    from {{ ref('int_state_intervals') }}
    where state = 'offline'
),

sized as (
    select *, count(*) over (partition by source, play_host, started_at) as same_host_same_start
    from offline
)

select
    source,
    key,
    title,
    play_host,
    started_at,
    started_basis,
    ended_at,
    end_reason,
    round(date_diff('minute', started_at, ended_at) / 60.0, 1) as hours_down,
    same_host_same_start >= {{ var('collective_min_ports') }} as collective,
    same_host_same_start as collective_size
from sized

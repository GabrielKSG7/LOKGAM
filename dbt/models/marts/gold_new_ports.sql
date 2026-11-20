-- Ports que a coleta viu chegar (os do primeiro retrato ficam de fora: a data deles é só um teto).
select
    port_id,
    title,
    game_title,
    platform,
    is_console,
    play_host,
    first_seen,
    listed,
    removed_at,
    state
from {{ ref('int_ports') }}
where first_seen_basis = 'added' and not hidden

-- Os ports listados agora, por plataforma de origem do jogo, com a situação da última conferência.
select
    platform,
    any_value(is_console) as is_console,
    count(*) as ports,
    count(distinct game_id) as games,
    count(*) filter (where play_host is not null) as playable,
    count(*) filter (where state = 'online') as online,
    count(*) filter (where state = 'unstable') as unstable,
    count(*) filter (where state = 'offline') as offline,
    count(*) filter (where state = 'unverified') as unverified,
    count(*) filter (where first_seen_basis = 'added') as added_since_baseline
from {{ ref('int_ports') }}
where listed
group by platform

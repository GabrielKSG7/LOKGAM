-- Cada port com o grupo de plataforma do jogo: o console de origem, "PC" ou "Não classificado".
select
    p.*,
    g.game_title,
    coalesce(g.origin, 'Não classificado') as platform,
    coalesce(g.console, false) as is_console,
    p.flagged or coalesce(g.flagged, false) as hidden
from {{ ref('stg_silver_ports') }} p
left join {{ ref('stg_silver_games') }} g using (game_id)

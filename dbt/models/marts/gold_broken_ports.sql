-- Versões fora do ar agora, com o jogo e a plataforma, e desde quando.
select
    o.source,
    o.key,
    p.port_id,
    coalesce(p.title, o.title) as title,
    coalesce(p.platform, 'Não classificado') as platform,
    coalesce(p.is_console, false) as is_console,
    o.play_host,
    o.started_at,
    o.started_basis,
    o.collective,
    coalesce(p.hidden, false) as hidden
from {{ ref('gold_outages') }} o
left join {{ ref('int_ports') }} p on list_contains(p.listings, o.source || ':' || o.key)
where o.ended_at is null

-- Os ports da camada prata: uma versão jogável (ou entrada sem versão) por linha, com o jogo.
select
    id as port_id,
    game_id,
    title,
    listings,
    play_host,
    cast(first_seen as timestamp) as first_seen,
    first_seen_basis,
    listed,
    cast(removed_at as timestamp) as removed_at,
    state,
    len(flags) > 0 as flagged
from {{ read_jsonl('silver/ports.jsonl', {
    'id': 'VARCHAR', 'game_id': 'VARCHAR', 'title': 'VARCHAR', 'listings': 'VARCHAR[]', 'play_host': 'VARCHAR',
    'first_seen': 'VARCHAR', 'first_seen_basis': 'VARCHAR', 'listed': 'BOOLEAN', 'removed_at': 'VARCHAR',
    'state': 'VARCHAR', 'flags': 'VARCHAR[]'}) }}

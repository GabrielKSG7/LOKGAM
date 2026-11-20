-- Os jogos da camada prata, com a plataforma em que nasceram quando ela é conhecida.
select id as game_id, title as game_title, origin, console, len(flags) > 0 as flagged
from {{ read_jsonl('silver/games.jsonl', {'id': 'VARCHAR', 'title': 'VARCHAR', 'origin': 'VARCHAR', 'console': 'BOOLEAN', 'flags': 'VARCHAR[]'}) }}

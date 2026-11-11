"""Camada prata: nomes de jogo, união de entradas, ligação com fichas e linha do tempo."""
import pytest

import collect_catalogs as cc
import silver
import validate
from metrics import base_summary

SOURCES = [{"id": "lista", "kind": "ports"}, {"id": "compat", "kind": "compatibility"}]
T0, T1, T2 = "2026-11-11T21:00:00Z", "2026-11-12T04:43:00Z", "2026-11-13T04:43:00Z"


def entry(title, play=None, source=None, key=None, extra=None):
    row = cc.new_entry(title, None, play, source, extra)
    row["key"] = key or cc.slug(title)
    return row


def ficha(id, title, play=None, source=None, platforms=("PC",)):
    return {"id": id, "title": title, "links": {"play": play, "source": source}, "game": {"platforms": list(platforms)}}


def bronze(entries, changes=(), compat=()):
    return {
        "runs": [{"source": "lista", "run_at": T0, "status": "ok"}, {"source": "lista", "run_at": T1, "status": "unchanged"}],
        "snapshots": {"lista": list(entries), "compat": list(compat)},
        "changes": {"lista": list(changes)},
    }


def build(entries, fichas=(), reference=(), **more):
    ports, games = silver.build_silver(SOURCES, bronze(entries, **more), list(fichas), list(reference))
    return {p["id"].split(":")[1]: p for p in ports}, {g["id"]: g for g in games}


@pytest.mark.parametrize("title, base, variant", [
    ("Super Mario 64 (sm64js)", "Super Mario 64", "sm64js"),
    ("Bendy and The Ink Machine (2)", "Bendy and The Ink Machine", None),
    ("Need for Speed: Most Wanted (2005) (NFSMW Online)", "Need for Speed: Most Wanted", "NFSMW Online"),
    ("Weltendämmerung (weltendaemmerung (spec-driven RE + web port))", "Weltendämmerung", "weltendaemmerung (spec-driven RE + web port)"),
    ("(tudo entre parênteses)", "(tudo entre parênteses)", None),
    ("Sem parênteses", "Sem parênteses", None),
])
def test_split_title(title, base, variant):
    assert silver.split_title(title) == (base, variant)


@pytest.mark.parametrize("a, b", [
    ("GTA V (Grand-V)", "Grand Theft Auto V"),
    ("GTA: Vice City (projetoescola)", "Grand Theft Auto: Vice City"),
    ("Quake II (q2.pieter.com)", "Quake 2"),
    ("Fear & Hunger", "Fear and Hunger"),
    ("American McGee’s Alice", "American McGee's Alice"),
    ("CTR: Crash Team Racing", "Crash Team Racing (High Octane)"),
    ("Plants vs. Zombies", "Plants vs Zombies"),
])
def test_same_game_under_different_spellings(a, b):
    assert silver.game_id(a) == silver.game_id(b)


def test_different_games_stay_apart():
    ids = [silver.game_id(t) for t in ("Quake", "Quake 2", "Quake 3", "Девятка (1994)", "ゼルダ", "I Spoke to God", "Super Mario 64 DS")]
    assert len(set(ids)) == len(ids) and silver.game_id("Super Mario 64") == "super-mario-64"


def test_flags_keep_some_titles_out_of_public_lists():
    assert silver.flags_of("Sex with Hitler") == ["adult", "sensitive"]
    assert silver.flags_of("Essex Racing") == [] and silver.flags_of("Super Mario 64") == []


def test_entries_with_the_same_playable_address_are_one_port():
    ports, games = build([
        entry("Deadseat", "https://a.example/deadseat/"), entry("The Deadseat", "https://a.example/deadseat"),
        entry("Doom (wasm)", "https://b.example/doom", "https://github.com/x/doom"), entry("Doom", None, "https://github.com/x/doom"),
    ])
    assert len(ports) == 3 and ports["deadseat"]["listings"] == ["lista:deadseat", "lista:the-deadseat"]
    assert (games["doom"]["ports"], games["doom"]["playable_ports"], games["doom"]["sources"]) == (2, 1, ["lista"])
    assert (ports["doom-wasm"]["variant"], ports["doom-wasm"]["hosting"], ports["doom"]["hosting"]) == ("wasm", "own", "none")


def test_ficha_finds_its_port_by_address_then_host_then_repository():
    entries = [
        entry("Halo: Combat Evolved", "https://autor.example/halo/halo.html"),
        entry("Halo: Combat Evolved (Combat Lab)", "https://autor.example/lab/"),
        entry("Flight of the Amazon Queen (ScummWeb)", "https://scumm.example/"),
        entry("Beneath a Steel Sky (ScummWeb)", "https://scumm.example/?game=sky"),
        entry("Quake", "https://outro.example/quake", "https://github.com/fulano/qwasm"),
        entry("Renomeado pela lista", "https://unico.example/jogo"),
    ]
    fichas = [
        ficha("halo", "Halo: Combat Evolved", "https://autor.example/halo/halo.html"),
        ficha("sky", "Beneath a Steel Sky", "https://scumm.example/"),
        ficha("quake", "Quake", "https://longe.example/", "https://github.com/fulano/qwasm"),
        ficha("unico", "Nome da ficha", "https://unico.example/jogo"),
    ]
    ports, games = build(entries, fichas)
    assert (ports["halo-combat-evolved"]["ficha_ids"], ports["halo-combat-evolved"]["ficha_match"]) == (["halo"], "play")
    assert ports["halo-combat-evolved-combat-lab"]["ficha_ids"] == []
    # Uma página que abre vários jogos: o endereço igual não basta, vale o jogo de mesmo nome.
    assert ports["flight-of-the-amazon-queen-scummweb"]["ficha_ids"] == []
    assert (ports["beneath-a-steel-sky-scummweb"]["ficha_ids"], ports["beneath-a-steel-sky-scummweb"]["ficha_match"]) == (["sky"], "host")
    assert (ports["quake"]["ficha_ids"], ports["quake"]["ficha_match"]) == (["quake"], "source")
    assert (ports["renomeado-pela-lista"]["ficha_ids"], ports["renomeado-pela-lista"]["ficha_match"]) == (["unico"], "play")
    assert games["halo-combat-evolved"]["ficha_ids"] == ["halo"] and games["halo-combat-evolved"]["ports"] == 2


def test_timeline_comes_from_what_the_collector_saw():
    gone = entry("Saiu", "https://saiu.example/")
    changes = [
        {"seen_at": T1, "change": "added", "key": "novo", "entry": {}, "fields": {}},
        {"seen_at": T1, "change": "changed", "key": "mudou", "entry": None, "fields": {"play_host": ["velho.example", "mudou.example"], "play_fingerprint": ["a", "b"]}},
        {"seen_at": T2, "change": "removed", "key": "saiu", "entry": gone, "fields": {}},
    ]
    ports, games = build([entry("Antigo", "https://antigo.example/"), entry("Novo", "https://novo.example/"), entry("Mudou", "https://mudou.example/")], changes=changes)
    assert (ports["antigo"]["first_seen"], ports["antigo"]["first_seen_basis"]) == (T0, "baseline")
    assert (ports["novo"]["first_seen"], ports["novo"]["first_seen_basis"]) == (T1, "added")
    assert ports["mudou"]["moves"] == [{"at": T1, "from": "velho.example", "to": "mudou.example"}]
    assert (ports["saiu"]["listed"], ports["saiu"]["removed_at"], ports["saiu"]["play_host"]) == (False, T2, "saiu.example")
    assert (games["saiu"]["ports"], games["saiu"]["listed_ports"], games["saiu"]["playable_ports"]) == (1, 0, 0)


def test_games_get_platform_origin_and_compatibility():
    entries = [entry("Super Mario 64 (sm64js)", "https://a.example/"), entry("Quake", "https://b.example/"), entry("Jogo Indie", "https://c.example/")]
    fichas = [ficha("q", "Quake", platforms=("PC", "Saturn")), ficha("só-ficha", "Driver 2", platforms=("PS1",))]
    compat = [entry("Quake", extra={"status": "playable"}), entry("Max Payne", extra={"status": "boots"})]
    _, games = build(entries, fichas, [{"title": "Super Mario 64", "platform": "N64"}], compat=compat)
    mario, quake = games["super-mario-64"], games["quake"]
    assert (mario["platforms"], mario["platforms_basis"], mario["origin"], mario["console"]) == (["N64"], "reference", "N64", True)
    assert (quake["platforms"], quake["platforms_basis"], quake["origin"], quake["console"]) == (["PC", "Saturn"], "ficha", "PC", False)
    assert quake["compat"] == {"compat": "playable"} and (games["max-payne"]["ports"], games["max-payne"]["compat"]) == (0, {"compat": "boots"})
    assert (games["jogo-indie"]["origin"], games["jogo-indie"]["console"]) == (None, None)
    assert (games["driver-2"]["ports"], games["driver-2"]["ficha_ids"], games["driver-2"]["console"]) == (0, ["só-ficha"], True)


def test_base_summary():
    entries = [entry("Super Mario 64 (a)", "https://a.example/"), entry("Super Mario 64 (b)", "https://b.example/"), entry("Quake", "https://c.example/"),
               entry("Sex with Hitler", "https://d.example/"), entry("Sex with Hitler (2)", "https://e.example/"), entry("Sex with Hitler (3)", "https://f.example/")]
    fichas = [ficha("q", "Quake", "https://c.example/")]
    ports, games = silver.build_silver(SOURCES, bronze(entries), fichas, [{"title": "Super Mario 64", "platform": "N64"}])
    out = base_summary(ports, games, fichas)
    assert (out["listings"], out["ports"], out["games"], out["classified_games"], out["console_games"], out["console_ports"]) == (6, 6, 3, 2, 1, 2)
    assert (out["fichas"], out["fichas_linked"], out["removed_ports"]) == (1, 1, 0)
    assert out["top_games"] == [{"title": "Super Mario 64", "ports": 2}, {"title": "Quake", "ports": 1}]
    assert out["by_origin"] == [{"platform": "N64", "ports": 2}]


def test_repo_silver_is_up_to_date_and_carries_no_address():
    ports, games = silver.current()
    assert (silver.SILVER / "ports.jsonl").read_text(encoding="utf-8") == ports
    assert (silver.SILVER / "games.jsonl").read_text(encoding="utf-8") == games
    assert "://" not in ports and "://" not in games
    assert silver.current() == (ports, games)
    assert validate.silver_checks() == []

"""Coletor de catálogos: leitura, identidade sem endereço, mudanças e proteções."""
import json
from types import SimpleNamespace

import pytest
import requests

import collect_catalogs as cc
import validate

CATALOG = """# Ultimate Catalog of Web Game Ports

![games](https://img.shields.io/badge/games-7-blue)

| Icon | Meaning |
|------|---------|
| ▶ | Opens a playable build in your browser |
| 📦 | Source code repository |

## # · 3

| Game | Play | Source |
|------|------|--------|
| Девятка (1994) | [▶ jogos.example](https://jogos.example/ports/nine-1994/index.html) |  |
| ⭐ -3 | [▶ espelho.example](https://espelho.example/?id=816) | [📦 fulano/-3](https://github.com/fulano/-3) |
| -b |  | [📦 web-ports/mods/tree/main/-b](https://github.com/web-ports/mods/tree/main/-b) |

[↑ back to top](#jump-to)

## A · 4

| Game | Play | Source |
|------|------|--------|
| ⭐ Alice | [▶ https://beltrana.github.io/alice-web/](https://beltrana.github.io/alice-web/) | [📦 beltrana/alice-web](https://github.com/beltrana/alice-web) |
| Amazing Alex | [▶ estudio.itch.io](https://estudio.itch.io/amazing-alex) | |
| Animal Crossing | [▶ WWW.Jogos.example](https://WWW.Jogos.example/Ports/AC/) | |
| Animal Crossing | [▶ outro.example](https://outro.example/ac) | |
"""

COMPAT = """# Compatibility

## Playable

| Title | Status | GOG |
|-------|--------|:---:|
| Max Payne | playable | |
| Need for Speed: Porsche Unleashed | playable\\* | |
| Unreal Gold | playable | ✓ |

## Stretch / in progress

| Title | Status | GOG |
|-------|--------|:---:|
| XIII | in progress | ✓ |
"""

SOURCE = {"id": "lista", "parser": "ultimate_catalog", "urls": ["https://a.example/lista.md", "https://b.example/lista.md"], "respect_robots": False}
STAMP = "2026-11-11T21:00:00Z"


class FakeSession:
    """Responde pelas páginas dadas; endereço que não está nelas dá erro de rede."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        if url not in self.pages:
            raise requests.ConnectionError(url)
        status, body = self.pages[url]
        return SimpleNamespace(status_code=status, content=body.encode("utf-8"), text=body)


def collect(text, previous=None, last_run=None, source=SOURCE):
    return cc.collect_source(source, STAMP, FakeSession({source["urls"][0]: (200, text)}), previous, last_run)


def test_reads_every_game_table_and_skips_the_legend():
    entries, quality = cc.parse_ultimate_catalog(CATALOG)
    assert [e["title"] for e in entries] == ["Девятка (1994)", "-3", "-b", "Alice", "Amazing Alex", "Animal Crossing", "Animal Crossing"]
    assert [e["section"] for e in entries] == ["#"] * 3 + ["A"] * 4
    assert quality == {"tables_skipped": 1, "tables": 2, "rows_seen": 7, "declared_rows": 7}


def test_entry_keeps_the_host_and_the_repo_owner_but_never_the_address():
    entries, _ = cc.parse_ultimate_catalog(CATALOG)
    star = entries[1]
    assert (star["play_host"], star["source_host"], star["source_owner"]) == ("espelho.example", "github.com", "fulano")
    assert entries[2]["play_host"] is None and entries[2]["source_owner"] == "web-ports"
    assert entries[5]["play_host"] == "jogos.example"
    for entry in entries:
        line = json.dumps(entry, ensure_ascii=False)
        assert "://" not in line and "tree/main" not in line and "?id=" not in line and "/ports" not in line.lower()
        assert "/" not in (entry["play_host"] or "") and "/" not in (entry["source_owner"] or "")


@pytest.mark.parametrize("address, host", [
    ("https://WWW.Example.org/a/b?c=1", "example.org"),
    ("jogos.example/x", "jogos.example"),
    ("https://sub.dominio.example:8443/", "sub.dominio.example"),
    ("https://localhost/x", None),
    ("mailto:alguem@example.org", None),
    ("#ancora", None),
])
def test_host_of(address, host):
    assert cc.host_of(address) == host


def test_fingerprint_follows_the_address_not_its_spelling():
    assert cc.fingerprint("https://Jogos.example/ports/ac/") == cc.fingerprint("http://jogos.example/ports/ac")
    assert cc.fingerprint("https://jogos.example/?id=1") != cc.fingerprint("https://jogos.example/?id=2")
    assert len(cc.fingerprint("https://jogos.example/")) == 12


def test_repo_owner_only_on_code_hosts():
    assert cc.repo_owner("https://github.com/fulano/jogo/tree/main/x") == "fulano"
    assert cc.repo_owner("https://fulano.github.io/jogo/") is None
    assert cc.repo_owner("https://github.com/") is None


def test_keys_are_unique_and_survive_other_alphabets():
    entries, _ = cc.parse_ultimate_catalog(CATALOG)
    assert cc.assign_keys(entries) == 1
    keys = [e["key"] for e in entries]
    assert keys[1:] == ["3", "b", "alice", "amazing-alex", "animal-crossing", "animal-crossing~2"]
    assert keys[0].startswith("1994-") and len(set(keys)) == 7
    assert cc.slug("Pokémon Édition") == "pokemon-edition"
    assert cc.slug("ゼルダ") != cc.slug("マリオ") and cc.slug("ゼルダ").startswith("t-")


def test_star_without_both_links_is_counted_as_a_reading_problem():
    text = "| Game | Play | Source |\n|---|---|---|\n| ⭐ Só jogável | [▶ a.example](https://a.example/) | |\n"
    assert cc.parse_ultimate_catalog(text)[1]["star_mismatch"] == 1


def test_reads_the_compatibility_list():
    entries, quality = cc.parse_bottleship_compat(COMPAT)
    assert [(e["title"], e["section"], e["extra"]) for e in entries] == [
        ("Max Payne", "Playable", {"status": "playable", "gog": "no"}),
        ("Need for Speed: Porsche Unleashed", "Playable", {"status": "playable", "gog": "no"}),
        ("Unreal Gold", "Playable", {"status": "playable", "gog": "yes"}),
        ("XIII", "Stretch / in progress", {"status": "in progress", "gog": "yes"}),
    ]
    assert quality["tables"] == 2 and all(e["play_host"] is None for e in entries)


def test_first_collection_is_a_baseline_without_changes():
    run, snapshot, changes = collect(CATALOG)
    assert (run["status"], run["baseline"], run["rows"], run["origin"]) == ("ok", True, 7, "a.example")
    assert changes == [] and (run["added"], run["removed"], run["changed"]) == (0, 0, 0)
    assert run["quality"]["key_collisions"] == 1 and "dropped" not in run["quality"]
    assert len(run["sha256"]) == 64 and sorted(snapshot) == sorted(e["key"] for e in snapshot.values())


def test_same_original_is_not_read_again():
    first, snapshot, _ = collect(CATALOG)
    run, new, changes = collect(CATALOG, snapshot, first)
    assert (run["status"], run["rows"], new, changes) == ("unchanged", 7, None, [])


def test_changes_between_two_snapshots():
    first, snapshot, _ = collect(CATALOG)
    edited = CATALOG.replace("| Amazing Alex | [▶ estudio.itch.io](https://estudio.itch.io/amazing-alex) | |\n", "")
    edited = edited.replace("https://outro.example/ac", "https://mudou.example/ac")
    edited += "| Arx | [▶ arx.example](https://arx.example/) | |\n"
    run, new, changes = collect(edited, snapshot, first)
    assert (run["status"], run["baseline"], run["added"], run["removed"], run["changed"]) == ("ok", False, 1, 1, 1)
    by_kind = {c["change"]: c for c in changes}
    assert by_kind["added"]["key"] == "arx" and by_kind["added"]["entry"]["play_host"] == "arx.example"
    assert by_kind["removed"]["key"] == "amazing-alex" and by_kind["removed"]["entry"]["play_host"] == "estudio.itch.io"
    assert by_kind["changed"]["key"] == "animal-crossing~2" and by_kind["changed"]["entry"] is None
    assert by_kind["changed"]["fields"]["play_host"] == ["outro.example", "mudou.example"]
    assert set(by_kind["changed"]["fields"]) == {"play_host", "play_fingerprint"}


def test_new_reader_version_starts_a_new_baseline(monkeypatch):
    first, snapshot, _ = collect(CATALOG)
    monkeypatch.setitem(cc.PARSERS, "ultimate_catalog", (cc.parse_ultimate_catalog, 2))
    run, new, changes = collect(CATALOG, snapshot, first)
    assert (run["status"], run["baseline"], run["parser_version"], changes) == ("ok", True, 2, [])


def test_a_collection_that_shrinks_too_much_replaces_nothing():
    first, snapshot, _ = collect(CATALOG)
    run, new, changes = collect("| Game | Play | Source |\n|---|---|---|\n| Só um | [▶ a.example](https://a.example/) | |\n", snapshot, first)
    assert (run["status"], run["reason"], new, changes) == ("failed", "shrunk", None, [])


def test_nothing_readable_is_a_failure():
    run, new, _ = collect("# Página de manutenção\n\nVolte mais tarde.\n")
    assert (run["status"], run["reason"], new) == ("failed", "parse_empty", None)


def test_falls_back_to_the_mirror_and_reports_the_last_failure():
    session = FakeSession({SOURCE["urls"][0]: (404, "sumiu"), SOURCE["urls"][1]: (200, CATALOG)})
    run, snapshot, _ = cc.collect_source(SOURCE, STAMP, session, None, None)
    assert (run["status"], run["origin"], len(snapshot)) == ("ok", "b.example", 7) and session.calls == SOURCE["urls"]
    run, snapshot, _ = cc.collect_source(SOURCE, STAMP, FakeSession({SOURCE["urls"][0]: (500, "erro")}), None, None)
    assert (run["status"], run["reason"], run["origin"], snapshot) == ("failed", "network", "b.example", None)


def test_robots_txt_is_obeyed_when_the_source_asks_for_it():
    polite = {**SOURCE, "urls": ["https://site.example/lista"], "respect_robots": True}
    blocked = FakeSession({"https://site.example/robots.txt": (200, "User-agent: *\nDisallow: /\n"), polite["urls"][0]: (200, CATALOG)})
    run, snapshot, _ = cc.collect_source(polite, STAMP, blocked, None, None)
    assert (run["status"], run["reason"], snapshot) == ("failed", "robots", None) and polite["urls"][0] not in blocked.calls
    allowed = FakeSession({"https://site.example/robots.txt": (404, ""), polite["urls"][0]: (200, CATALOG)})
    assert cc.collect_source(polite, STAMP, allowed, None, None)[0]["status"] == "ok"
    unreachable = FakeSession({polite["urls"][0]: (200, CATALOG)})
    assert cc.collect_source(polite, STAMP, unreachable, None, None)[0]["reason"] == "robots"


def test_store_writes_a_sorted_snapshot_the_changes_and_the_run(tmp_path):
    first, snapshot, _ = collect(CATALOG)
    cc.store(first, snapshot, [], tmp_path)
    again = cc.load_snapshot("lista", tmp_path)
    assert again == snapshot and list(again) == sorted(again)
    edited = CATALOG + "| Arx | [▶ arx.example](https://arx.example/) | |\n"
    second, new, changes = collect(edited, again, cc.last_good_run(validate.load_jsonl(tmp_path / "runs.jsonl"), "lista"))
    cc.store(second, new, changes, tmp_path)
    bronze = validate.load_bronze(tmp_path)
    assert [r["status"] for r in bronze["runs"]] == ["ok", "ok"] and len(bronze["snapshots"]["lista"]) == 8
    assert [(c["change"], c["key"], c["seen_at"], c["source"]) for c in bronze["changes"]["lista"]] == [("added", "arx", STAMP, "lista")]
    for rows, name in ((bronze["runs"], "bronze_run"), (bronze["snapshots"]["lista"], "bronze_entry"), (bronze["changes"]["lista"], "bronze_change")):
        assert validate.schema_errors(rows, f"{name}.schema.json", "source" if name == "bronze_run" else "key") == []
    assert "://" not in (tmp_path / "lista" / "snapshot.jsonl").read_text(encoding="utf-8")


def test_summary_line():
    first, snapshot, _ = collect(CATALOG)
    same, _, _ = collect(CATALOG, snapshot, first)
    failed, _, _ = collect("nada")
    assert cc.summary_line([first, same, failed], STAMP) == (
        "Coleta de catálogos de 2026-11-11 21:00 UTC: lista 7 entradas (retrato inicial); lista sem mudanças; lista falhou (parse_empty)"
    )


def test_every_reader_has_a_place_in_the_source_schema():
    schema = validate.load_json(validate.ROOT / "schema" / "source.schema.json")
    assert set(schema["properties"]["parser"]["enum"]) - {None} == set(cc.PARSERS)


def test_pipeline_rules():
    catalogs = [{"id": "cat"}]
    good = {"id": "f", "catalog_id": "cat", "status": "active", "parser": "ultimate_catalog", "urls": ["https://a.example/x"]}
    empty = {"runs": [], "snapshots": {}, "changes": {}}
    assert validate.pipeline_errors([good], catalogs, empty) == []
    assert any("catálogo inexistente" in e for e in validate.pipeline_errors([{**good, "catalog_id": "outro"}], catalogs, empty))
    assert any("leitor e de endereço" in e for e in validate.pipeline_errors([{**good, "urls": []}], catalogs, empty))
    assert any("não guarda endereço" in e for e in validate.pipeline_errors([{**good, "status": "blocked"}], catalogs, empty))
    stray = {"runs": [{"source": "x"}], "snapshots": {"x": [{"key": "b"}, {"key": "a"}]}, "changes": {}}
    errors = validate.pipeline_errors([good], catalogs, stray)
    assert any("pasta sem fonte" in e for e in errors) and any("fora de ordem" in e for e in errors) and any("fonte desconhecida" in e for e in errors)

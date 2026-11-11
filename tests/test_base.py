"""A base do repositório passa na validação, e as regras de curadoria pegam o que devem pegar."""
from __future__ import annotations

import copy

import build
import format_base
import validate


def test_repository_base_is_valid():
    assert validate.validate() == []


def approved_port():
    ports, _, _ = validate.load_base()
    return copy.deepcopy(next(p for p in ports if p["curation"]["state"] == "approved"))


def errors_for(port, checks=None):
    checks = [{"port_id": port["id"]}] if checks is None else checks
    return validate.rule_errors([port], [], checks)


def test_approved_port_passes_alone():
    assert errors_for(approved_port()) == []


def test_bundled_port_cannot_be_approved():
    port = approved_port()
    port["rights"]["status"] = "bundled"
    assert any("bundled" in line for line in errors_for(port))


def test_rejected_port_keeps_no_play_link():
    port = approved_port()
    port["curation"]["state"] = "rejected"
    assert any("rejeitada" in line for line in errors_for(port))


def test_rejected_port_needs_a_cover_for_the_no_link_shelf():
    port = approved_port()
    port["curation"]["state"] = "rejected"
    port["links"]["play"] = None
    del port["label"]
    assert any("sem capa" in line for line in errors_for(port))


def test_own_copy_route_must_point_to_a_port_that_asks_for_the_players_copy():
    ports, _, _ = validate.load_base()
    target = copy.deepcopy(
        next(p for p in ports if p["rights"]["status"] == "byo_files" and p["curation"]["state"] != "rejected")
    )
    port = approved_port()
    port["id"] = "outra-ficha"
    port["own_copy_route"] = target["id"]
    checks = [{"port_id": port["id"]}, {"port_id": target["id"]}]
    assert not any("own_copy_route" in line for line in validate.rule_errors([port, target], [], checks))
    port["own_copy_route"] = "ficha-que-nao-existe"
    assert any("não existe" in line for line in validate.rule_errors([port, target], [], checks))
    port["own_copy_route"] = target["id"]
    target["rights"]["status"] = "bundled"
    assert any("own_copy_route" in line for line in validate.rule_errors([port, target], [], checks))


def test_decided_port_needs_a_source_but_a_pending_one_does_not():
    port = approved_port()
    port["curation"]["sources"] = []
    assert any("fonte" in line for line in errors_for(port))
    port["curation"]["state"] = "pending"
    assert not any("fonte" in line for line in errors_for(port))


def catalog(**changes):
    row = {"id": "x", "name": "X", "kind": "directory", "hosts_games": False, "url": "https://example.org/",
           "summary": "s", "added": "2026-11-11", "sources": [{"title": "t", "url": "https://example.org/fonte"}]}
    return {**row, **changes}


def test_catalog_keeps_a_link_only_when_a_source_says_it_hosts_no_games():
    assert validate.catalog_errors([catalog()]) == []
    assert validate.catalog_errors([catalog(hosts_games=None, url=None, sources=[])]) == []
    for hosts in (True, None):
        assert any("guarda url" in line for line in validate.catalog_errors([catalog(hosts_games=hosts)]))
    assert any("exige fonte" in line for line in validate.catalog_errors([catalog(sources=[])]))
    assert any("exige fonte" in line for line in validate.catalog_errors([catalog(hosts_games=True, url=None, sources=[])]))


def test_storefront_carries_no_address_of_catalogs_that_host_games():
    ports, events, checks = validate.load_base()
    payload = build.storefront_payload(ports, events, checks, validate.load_catalogs())
    assert payload["catalogs"], "o teste precisa de catálogos na base"
    for row in payload["catalogs"]:
        assert row["hosts_games"] is False or row["url"] is None


def test_ports_file_is_in_canonical_format():
    current = format_base.PORTS.read_text(encoding="utf-8")
    assert current == format_base.format_ports(validate.load_json(format_base.PORTS))


def test_approved_port_needs_a_link_check():
    assert any("conferência" in line for line in errors_for(approved_port(), checks=[]))


def test_own_copy_seal_needs_a_required_file():
    port = approved_port()
    port["rights"]["status"] = "byo_files"
    port["requirements"]["user_files"] = []
    assert any("byo_files" in line for line in errors_for(port))


def test_robot_rows_need_a_reason():
    row = {"port_id": "x", "checked_at": "2026-11-11T06:17:00Z", "state": "online", "method": "link_checker"}
    errors = validate.schema_errors([row], "check.schema.json", "port_id")
    assert any("reason" in line for line in errors)
    manual = {"port_id": "x", "checked_at": "2026-11-10", "state": "online", "method": "manual"}
    assert validate.schema_errors([manual], "check.schema.json", "port_id") == []


def test_pages_only_carry_links_of_approved_ports():
    ports, events, checks = validate.load_base()
    payload = build.storefront_payload(ports, events, checks)
    for card in payload["ports"]:
        if card["curation"]["state"] != "approved":
            assert card["links"]["play"] is None
    pending_links = [p["links"]["play"] for p in ports if p["curation"]["state"] == "pending" and p["links"]["play"]]
    assert pending_links, "o teste precisa de ao menos uma ficha em análise com link"
    for page in (build.embed(payload), build.embed(build.observatory_payload(ports, events, checks))):
        assert not any(link in page for link in pending_links)


def test_embedded_json_cannot_close_the_script_tag():
    assert "</script>" not in build.embed({"texto": "</script><script>alert(1)</script>"})

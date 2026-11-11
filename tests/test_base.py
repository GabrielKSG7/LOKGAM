"""A base do repositório passa na validação, e as regras de curadoria pegam o que devem pegar."""
from __future__ import annotations

import copy

import build
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

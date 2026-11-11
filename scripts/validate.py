#!/usr/bin/env python3
"""Valida a base da Locadora: formato (JSON Schema) e regras de curadoria.

Uso: python3 scripts/validate.py
Sai com código 1 se houver qualquer erro.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
LISTABLE = {"official", "free", "demo", "byo_files"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_base() -> tuple[list[dict], list[dict], list[dict]]:
    return (
        load_json(ROOT / "data" / "ports.json"),
        load_json(ROOT / "data" / "events.json"),
        load_jsonl(ROOT / "data" / "checks.jsonl"),
    )


def schema_errors(rows: list[dict], schema_name: str, key: str) -> list[str]:
    validator = Draft202012Validator(
        load_json(ROOT / "schema" / schema_name), format_checker=FormatChecker()
    )
    errors = []
    for i, row in enumerate(rows):
        label = row.get(key, f"linha {i + 1}")
        for err in validator.iter_errors(row):
            where = "/".join(str(p) for p in err.absolute_path) or "(raiz)"
            errors.append(f"{schema_name} [{label}] {where}: {err.message}")
    return errors


def rule_errors(ports: list[dict], events: list[dict], checks: list[dict]) -> list[str]:
    errors = []
    ids = [p["id"] for p in ports]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"ports: id repetido: {dup}")
    known = set(ids)
    event_ids = [e["id"] for e in events]
    for dup in sorted({i for i in event_ids if event_ids.count(i) > 1}):
        errors.append(f"events: id repetido: {dup}")
    for e in events:
        if e["port_id"] not in known:
            errors.append(f"events [{e['id']}]: port_id desconhecido: {e['port_id']}")
    for c in checks:
        if c["port_id"] not in known:
            errors.append(f"checks: port_id desconhecido: {c['port_id']}")
    checked = {c["port_id"] for c in checks}
    by_id = {p["id"]: p for p in ports}

    for p in ports:
        pid, state = p["id"], p["curation"]["state"]
        status = p["rights"]["status"]
        files = p["requirements"]["user_files"]
        if state == "approved":
            if not p["links"]["play"]:
                errors.append(f"{pid}: ficha aprovada sem links.play")
            if status not in LISTABLE:
                errors.append(f"{pid}: ficha aprovada com rights.status '{status}'")
            if p["port"]["technique"] == "unknown":
                errors.append(f"{pid}: ficha aprovada com técnica desconhecida")
            if p["curation"]["risk"] is None:
                errors.append(f"{pid}: ficha aprovada sem risco avaliado")
            if "label" not in p:
                errors.append(f"{pid}: ficha aprovada sem capa (label)")
            if not p["requirements"]["controls"]:
                errors.append(f"{pid}: ficha aprovada sem controles")
            if pid not in checked:
                errors.append(f"{pid}: ficha aprovada sem nenhuma conferência de link")
            if status == "byo_files" and not any(f["needed_for"] == "play" for f in files):
                errors.append(f"{pid}: selo 'byo_files' sem arquivo exigido para jogar")
            if status == "demo" and not any(f["needed_for"] == "full_game" for f in files):
                errors.append(f"{pid}: selo 'demo' sem arquivo que libere o jogo completo")
            if status in {"official", "free"} and any(f["needed_for"] == "play" for f in files):
                errors.append(f"{pid}: selo '{status}' não combina com arquivo exigido para jogar")
        if state == "rejected" and p["links"]["play"]:
            errors.append(f"{pid}: ficha rejeitada não guarda links.play")
        if state == "rejected" and "label" not in p:
            errors.append(f"{pid}: ficha rejeitada sem capa (label)")
        route = p.get("own_copy_route")
        if route is not None:
            target = by_id.get(route)
            if target is None or route == pid:
                errors.append(f"{pid}: own_copy_route aponta para ficha que não existe: {route}")
            elif target["rights"]["status"] != "byo_files" or target["curation"]["state"] == "rejected":
                errors.append(f"{pid}: own_copy_route precisa apontar para ficha 'byo_files' que não esteja rejeitada")
        if status == "bundled" and state != "rejected":
            errors.append(f"{pid}: port que embute o jogo precisa estar rejeitado")
    return errors


def validate() -> list[str]:
    ports, events, checks = load_base()
    return (
        schema_errors(ports, "port.schema.json", "id")
        + schema_errors(events, "event.schema.json", "id")
        + schema_errors(checks, "check.schema.json", "port_id")
        + rule_errors(ports, events, checks)
    )


def main() -> int:
    errors = validate()
    for line in errors:
        print("ERRO", line)
    ports, events, checks = load_base()
    states = [p["curation"]["state"] for p in ports]
    print(
        f"{len(ports)} fichas ({states.count('approved')} aprovadas, "
        f"{states.count('pending')} em análise, {states.count('rejected')} rejeitadas), "
        f"{len(events)} eventos, {len(checks)} conferências, {len(errors)} erros"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Gera docs/index.html: a vitrine com a base embutida, em um arquivo só.

Uso: python3 scripts/build.py
Valida a base antes; não gera nada se houver erro.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from validate import ROOT, load_base, validate

PLACEHOLDER = "__CATALOGO__"


def latest_checks(checks: list[dict]) -> dict[str, dict]:
    """Última conferência de cada ficha. Empate de data fica com a linha mais recente do arquivo."""
    latest: dict[str, dict] = {}
    for check in checks:
        current = latest.get(check["port_id"])
        if current is None or check["checked_at"] >= current["checked_at"]:
            latest[check["port_id"]] = check
    return latest


def main() -> int:
    errors = validate()
    if errors:
        for line in errors:
            print("ERRO", line)
        print("Base inválida: nada foi gerado.")
        return 1

    ports, events, checks = load_base()
    latest = latest_checks(checks)
    for port in ports:
        check = latest.get(port["id"])
        port["status"] = {
            "state": check["state"] if check else "unverified",
            "checked_at": check["checked_at"] if check else None,
            "note": check.get("note", "") if check else "",
        }
        if port["curation"]["state"] == "rejected":
            port["links"]["play"] = None

    payload = {
        "base_date": max(c["checked_at"] for c in checks)[:10],
        "ports": ports,
        "events": events,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    template = (ROOT / "web" / "template.html").read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        print(f"O template precisa ter exatamente um {PLACEHOLDER}.")
        return 1
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(template.replace(PLACEHOLDER, data), encoding="utf-8")
    print(f"Gerado {out.relative_to(ROOT)} ({out.stat().st_size / 1024:.0f} KB) com {len(ports)} fichas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

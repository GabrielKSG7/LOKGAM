#!/usr/bin/env python3
"""Gera o site em docs/: a vitrine e o observatório, cada um em um arquivo só.

Uso: python3 scripts/build.py
Valida a base antes; não gera nada se houver erro.

A saída depende só dos arquivos do repositório. Tudo que depende da hora
(há quanto tempo foi a última conferência) é calculado no navegador.
"""
from __future__ import annotations

import json
import sys

import silver
from metrics import base_summary, build_metrics, by_port, catalog_coverage, check_summary, is_monitored, latest
from validate import ROOT, load_base, load_bronze, load_catalogs, load_jsonl, load_sources, validate

REPO_URL = "https://github.com/GabrielKSG7/LOKGAM"
# Quantas conferências recentes cada ficha da vitrine mostra.
HISTORY_LENGTH = 30


def embed(data: dict) -> str:
    """JSON pronto para ir dentro de uma tag <script>."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render(template_name: str, replacements: dict[str, str]) -> str:
    page = (ROOT / "web" / template_name).read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        if page.count(placeholder) != 1:
            raise SystemExit(f"{template_name} precisa ter exatamente um {placeholder}.")
        page = page.replace(placeholder, value)
    return page


def storefront_payload(ports: list[dict], events: list[dict], checks: list[dict], catalogs: list[dict] | None = None) -> dict:
    grouped = by_port(checks)
    stamps = [check["checked_at"] for check in checks]
    cards = []
    for port in ports:
        card = json.loads(json.dumps(port))
        if port["curation"]["state"] != "approved":
            # Só ficha aprovada leva link para a página.
            card["links"]["play"] = None
        if is_monitored(port):
            history = grouped.get(port["id"], [])
            card["seen"] = check_summary(latest(history, observed_only=True))
            card["last"] = check_summary(latest(history))
            card["history"] = [[row["checked_at"], row["state"]] for row in history[-HISTORY_LENGTH:]]
        cards.append(card)
    return {
        "repo": REPO_URL,
        "last_check": max(stamps) if stamps else None,
        "ports": cards,
        "events": events,
        "catalogs": catalogs or [],
    }


def observatory_payload(ports: list[dict], events: list[dict], checks: list[dict]) -> dict:
    by_id = {port["id"]: port for port in ports}
    timeline = [
        {
            **event,
            "title": by_id[event["port_id"]]["title"],
            "port_name": by_id[event["port_id"]]["port"].get("name", ""),
        }
        for event in events
    ]
    return {
        "repo": REPO_URL,
        **build_metrics(ports, events, checks),
        "events": timeline,
        "catalogs": catalog_coverage(load_sources(), load_catalogs(), load_bronze()),
        "base": base_summary(load_jsonl(silver.SILVER / "ports.jsonl"), load_jsonl(silver.SILVER / "games.jsonl"), ports),
    }


def main() -> int:
    # A camada prata é derivada do resto da base: refaz antes de validar e de gerar as páginas.
    silver.main()
    errors = validate()
    if errors:
        for line in errors:
            print("ERRO", line)
        print("Base inválida: nada foi gerado.")
        return 1

    ports, events, checks = load_base()
    shared = {
        "/*__BASE_CSS__*/": (ROOT / "web" / "base.css").read_text(encoding="utf-8"),
        "/*__BASE_JS__*/": (ROOT / "web" / "base.js").read_text(encoding="utf-8"),
    }
    pages = {
        "index.html": render("vitrine.html", {**shared, "__DADOS__": embed(storefront_payload(ports, events, checks, load_catalogs()))}),
        "observatorio/index.html": render(
            "observatorio.html", {**shared, "__DADOS__": embed(observatory_payload(ports, events, checks))}
        ),
    }
    docs = ROOT / "docs"
    for name, page in pages.items():
        out = docs / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        print(f"Gerado docs/{name} ({out.stat().st_size / 1024:.0f} KB)")
    # Sem isto o GitHub Pages passa o site pelo Jekyll à toa.
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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


MOVED = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>LOKGAM</title>
<link rel="canonical" href="../">
<meta http-equiv="refresh" content="0; url=../">
<script>location.replace('../' + location.hash);</script>
</head>
<body><p>O observatório agora é a <a href="../">página inicial da LOKGAM</a>.</p></body>
</html>
"""


GOLD = ROOT / "data" / "gold"


def gold_payload() -> dict | None:
    """Os achados da camada ouro para a fonte de ports principal. Nada se o dbt ainda não rodou."""
    if not (GOLD / "findings.json").exists():
        return None
    tables = {name: json.loads((GOLD / f"{name}.json").read_text(encoding="utf-8"))
              for name in ("findings", "daily_status", "collective_outages", "outages")}
    sources = [s["id"] for s in load_sources() if s["status"] == "active" and s["kind"] == "ports"]
    main = next((s for s in sources if any(row["source"] == s for row in tables["findings"])), None)
    if main is None:
        return None
    pick = lambda name: [row for row in tables[name] if row["source"] == main]
    isolated = [row for row in pick("outages") if not row["collective"] and row["started_basis"] == "observed"]
    return {
        "source": main,
        "findings": pick("findings")[0],
        "daily": sorted(pick("daily_status"), key=lambda row: row["run_at"]),
        "collective": sorted(pick("collective_outages"), key=lambda row: (row["started_at"], row["play_host"])),
        "isolated": sorted(({k: row[k] for k in ("title", "play_host", "started_at", "ended_at", "end_reason")} for row in isolated),
                           key=lambda row: (row["started_at"], row["title"])),
    }


def evolution_payload() -> dict:
    """O que a página de evolução mostra: a base dia a dia, por plataforma, os novos e os quebrados."""
    read = lambda name: json.loads((GOLD / f"{name}.json").read_text(encoding="utf-8"))
    return {
        "repo": REPO_URL,
        "days": sorted(read("evolution_daily"), key=lambda row: row["day"]),
        "platforms": read("platform_summary"),
        "new_ports": read("new_ports"),
        # Quebrados: sem os títulos marcados como adultos ou sensíveis, e sem chave nem endereço.
        "broken": [
            {k: row[k] for k in ("title", "platform", "is_console", "play_host", "started_at", "started_basis", "collective")}
            for row in read("broken_ports") if not row["hidden"]
        ],
    }


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
        "base": base_summary(
            load_jsonl(silver.SILVER / "ports.jsonl"), load_jsonl(silver.SILVER / "games.jsonl"), ports,
            checked_at=max((run["run_at"] for run in load_bronze()["status_runs"] if run["status"] == "ok"), default=None),
        ),
        "gold": gold_payload(),
        # O que a página inicial mostra em "Onde jogar": só fichas aprovadas, e sem o endereço.
        "storefront": [
            {"id": port["id"], "title": port["title"], "status": port["rights"]["status"]}
            for port in ports
            if port["curation"]["state"] == "approved"
        ],
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
    data_css = {"/*__DADOS_CSS__*/": (ROOT / "web" / "dados.css").read_text(encoding="utf-8")}
    pages = {
        "index.html": render("observatorio.html", {**shared, **data_css, "__DADOS__": embed(observatory_payload(ports, events, checks))}),
        "vitrine/index.html": render(
            "vitrine.html", {**shared, "__DADOS__": embed(storefront_payload(ports, events, checks, load_catalogs()))}
        ),
        "evolucao/index.html": render("evolucao.html", {**shared, **data_css, "__DADOS__": embed(evolution_payload())}),
        # O observatório morava aqui antes de virar a página inicial.
        "observatorio/index.html": MOVED,
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

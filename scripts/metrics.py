#!/usr/bin/env python3
"""Métricas do observatório, calculadas das três tabelas da base.

Tudo aqui é função pura: recebe as listas já carregadas e devolve dicionários
prontos para virar JSON. Rodar o arquivo mostra o resultado no terminal.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

# Disponibilidade só vira porcentagem depois deste tanto de conferências válidas.
MIN_SAMPLES = 8
# Quantas conferências recentes a faixa de histórico mostra.
STRIP_LENGTH = 40
RIGHTS_ACTIONS = {"dmca_notice", "removal"}
OUTAGES = {"outage"}


def is_monitored(port: dict) -> bool:
    return bool(port["links"]["play"]) and port["curation"]["state"] in ("approved", "pending")


def by_port(checks: list[dict]) -> dict[str, list[dict]]:
    """Conferências de cada ficha, da mais antiga para a mais recente.

    A ordenação é estável: no empate de data vale a ordem do arquivo. Datas sem
    hora ("2026-11-10") ficam antes de qualquer horário do mesmo dia.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for check in checks:
        grouped[check["port_id"]].append(check)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["checked_at"])
    return grouped


def latest(rows: list[dict], observed_only: bool = False) -> dict | None:
    """Última conferência. Com `observed_only`, a última que de fato viu o site."""
    for row in reversed(rows):
        if not observed_only or row["state"] != "unverified":
            return row
    return None


def check_summary(check: dict | None) -> dict | None:
    if check is None:
        return None
    keys = ("checked_at", "state", "method", "reason", "http_status", "response_ms", "note")
    return {key: check[key] for key in keys if check.get(key) not in (None, "")}


def availability(ports: list[dict], checks: list[dict]) -> list[dict]:
    """Uma linha por port conferido: quantas vezes foi visto e quantas estava no ar.

    Conferência em que o site barrou o robô ("unverified") não entra na conta,
    nem a favor nem contra.
    """
    grouped = by_port(checks)
    rows = []
    for port in ports:
        if not is_monitored(port):
            continue
        history = grouped.get(port["id"], [])
        states = Counter(row["state"] for row in history)
        observed = len(history) - states["unverified"]
        rows.append(
            {
                "id": port["id"],
                "title": port["title"],
                "port_name": port["port"].get("name", ""),
                "curation": port["curation"]["state"],
                "checks": len(history),
                "observed": observed,
                "online": states["online"],
                "unstable": states["unstable"],
                "offline": states["offline"],
                "blocked": states["unverified"],
                "pct": round(states["online"] / observed, 4) if observed >= MIN_SAMPLES else None,
                "first_check": history[0]["checked_at"] if history else None,
                "seen": check_summary(latest(history, observed_only=True)),
                "last": check_summary(latest(history)),
                "strip": [[row["checked_at"], row["state"]] for row in history[-STRIP_LENGTH:]],
            }
        )
    return rows


def _months(first: str, last: str) -> list[str]:
    year, month = int(first[:4]), int(first[5:7])
    months = []
    while f"{year:04d}-{month:02d}" <= last:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def events_by_month(events: list[dict], until: str | None = None) -> list[dict]:
    """Ações de donos de jogos e quedas, mês a mês, sem pular mês vazio."""
    counted = [e for e in events if e["kind"] in RIGHTS_ACTIONS | OUTAGES]
    if not counted:
        return []
    months = [e["date"][:7] for e in counted]
    last = max(max(months), (until or "")[:7])
    rights = Counter(e["date"][:7] for e in counted if e["kind"] in RIGHTS_ACTIONS)
    outages = Counter(e["date"][:7] for e in counted if e["kind"] in OUTAGES)
    return [
        {"month": month, "rights_actions": rights[month], "outages": outages[month]}
        for month in _months(min(months), last)
    ]


def actors(events: list[dict], ports: list[dict]) -> list[dict]:
    """Quem notificou ou removeu, com os ports atingidos."""
    titles = {p["id"]: p["title"] for p in ports}
    grouped: dict[str, list[str]] = defaultdict(list)
    for event in events:
        if event["kind"] in RIGHTS_ACTIONS:
            grouped[event["actor"] or ""].append(titles[event["port_id"]])
    rows = [{"actor": actor, "count": len(names), "ports": sorted(set(names))} for actor, names in grouped.items()]
    return sorted(rows, key=lambda row: (row["actor"] == "", -row["count"], row["actor"].lower()))


def composition(ports: list[dict]) -> list[dict]:
    """Quantas fichas de cada técnica estão em cada estado de curadoria."""
    grouped: dict[str, Counter] = defaultdict(Counter)
    for port in ports:
        grouped[port["port"]["technique"]][port["curation"]["state"]] += 1
    rows = [
        {
            "technique": technique,
            "approved": counts["approved"],
            "pending": counts["pending"],
            "rejected": counts["rejected"],
            "total": sum(counts.values()),
        }
        for technique, counts in grouped.items()
    ]
    return sorted(rows, key=lambda row: (row["technique"] == "unknown", -row["total"], row["technique"]))


def build_metrics(ports: list[dict], events: list[dict], checks: list[dict]) -> dict:
    stamps = [check["checked_at"] for check in checks]
    last_check = max(stamps) if stamps else None
    return {
        "min_samples": MIN_SAMPLES,
        "totals": {
            "ports": len(ports),
            "events": len(events),
            "checks": len(checks),
            "first_check": min(stamps) if stamps else None,
            "last_check": last_check,
        },
        "availability": availability(ports, checks),
        "events_by_month": events_by_month(events, until=last_check),
        "actors": actors(events, ports),
        "composition": composition(ports),
    }


if __name__ == "__main__":
    from validate import load_base

    json.dump(build_metrics(*load_base()), sys.stdout, ensure_ascii=False, indent=2)
    print()

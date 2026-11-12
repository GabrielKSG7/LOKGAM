#!/usr/bin/env python3
"""Confere, uma vez por dia, se cada versão jogável listada nos catálogos responde.

Os endereços vêm do próprio catálogo, lido na hora, e só existem na memória durante a
execução. O que fica gravado é a situação de cada entrada, pela chave dela:

    data/bronze/<fonte>/status.jsonl          a situação atual de cada entrada e desde quando
    data/bronze/<fonte>/status_changes.jsonl  cada troca de situação; só cresce
    data/bronze/status_runs.jsonl             uma linha por fonte a cada conferência

A primeira vez que uma entrada é conferida não conta como troca: é o ponto de partida.

Uso: python3 scripts/check_catalog.py [--only ID ...] [--dry-run] [--summary-file CAMINHO]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import collect_catalogs as cc
from check_links import NETWORK_REASONS, check_url, new_session
from validate import load_json, load_jsonl

WORKERS = 8          # domínios conferidos ao mesmo tempo
PAUSE_SECONDS = 0.3  # intervalo entre dois pedidos ao mesmo domínio
BUDGET_SECONDS = 15 * 60
STATES = ("online", "unstable", "offline", "unverified")


def _check(session, url: str):
    return check_url(session, url, attempts=2, pause=2, timeout=(8, 15))


def addresses(source: dict, session) -> tuple[dict[str, str] | None, str | None]:
    """Chave -> endereço jogável, lido do catálogo agora. Nada disto é gravado."""
    got = cc.fetch(session, source)
    if not got.ok:
        return None, got.reason
    parse, _ = cc.PARSERS[source["parser"]]
    found: list = []
    entries, _ = parse(got.text, addresses=found)
    cc.assign_keys(entries)
    return {entry["key"]: url for entry, url in zip(entries, found) if url}, None


def check_targets(targets: dict[str, str], check: Callable = _check, session_factory: Callable = new_session,
                  workers: int = WORKERS, pause: float = PAUSE_SECONDS, budget: float = BUDGET_SECONDS) -> dict[str, dict]:
    """Confere cada endereço. Um domínio por vez em cada fila, para não sobrecarregar ninguém."""
    by_host: dict[str, list] = defaultdict(list)
    for key, url in sorted(targets.items()):
        by_host[cc.host_of(url) or ""].append((key, url))
    started = time.monotonic()

    def one_host(items: list) -> dict[str, dict]:
        session, out = session_factory(), {}
        for i, (key, url) in enumerate(items):
            if time.monotonic() - started > budget:
                break  # o que ficou de fora mantém a situação anterior
            if i:
                time.sleep(pause)
            probe, verdict = check(session, url)
            out[key] = {"state": verdict.state, "reason": verdict.reason, "http_status": probe.status}
        return out

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(one_host, by_host.values()):
            results.update(part)
    return results


def apply(previous: dict[str, dict], results: dict[str, dict], keys: set[str], stamp: str) -> tuple[dict[str, dict], list[dict]]:
    """Situação nova de cada entrada e as trocas em relação à anterior."""
    status, transitions = {}, []
    for key in sorted(keys):
        before, now = previous.get(key), results.get(key)
        if now is None:
            if before:
                status[key] = before
            continue
        since = before["since"] if before and before["state"] == now["state"] else stamp
        if before and before["state"] != now["state"]:
            transitions.append({"at": stamp, "key": key, "from": before["state"], "to": now["state"],
                                "reason": now["reason"], "http_status": now["http_status"]})
        status[key] = {"key": key, **now, "since": since}
    return status, transitions


def check_source(source: dict, stamp: str, previous: dict[str, dict], snapshot_keys: set[str],
                 session=None, **options) -> tuple[dict, dict[str, dict] | None, list[dict]]:
    started = time.monotonic()
    run = {"run_at": stamp, "source": source["id"], "status": "failed", "reason": None, "targets": 0, "checked": 0,
           **{state: 0 for state in STATES}, "transitions": 0, "seconds": 0}
    found, reason = addresses(source, session or cc.new_session())
    if found is None:
        run["reason"] = reason
        return run, None, []
    targets = {key: url for key, url in found.items() if key in snapshot_keys}
    results = check_targets(targets, **options)
    run.update(targets=len(targets), checked=len(results), seconds=round(time.monotonic() - started))
    if results and all(row["reason"] in NETWORK_REASONS for row in results.values()):
        run.update(status="skipped", reason="network_down")  # o problema é a rede do robô
        return run, None, []
    status, transitions = apply(previous, results, set(targets), stamp)
    tally = Counter(row["state"] for row in status.values())
    run.update(status="ok", transitions=len(transitions), **{state: tally[state] for state in STATES})
    return run, status, transitions


def _line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False) + "\n"


def load_status(source_id: str, root: Path = cc.BRONZE) -> dict[str, dict]:
    path = root / source_id / "status.jsonl"
    return {row["key"]: row for row in load_jsonl(path)} if path.exists() else {}


def store(run: dict, status: dict[str, dict] | None, transitions: list[dict], root: Path = cc.BRONZE) -> None:
    folder = root / run["source"]
    if status is not None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "status.jsonl").write_text("".join(_line(status[key]) for key in sorted(status)), encoding="utf-8")
        if transitions:
            with (folder / "status_changes.jsonl").open("a", encoding="utf-8") as out:
                for row in transitions:
                    out.write(_line({"source": run["source"], **row}))
    root.mkdir(parents=True, exist_ok=True)
    with (root / "status_runs.jsonl").open("a", encoding="utf-8") as out:
        out.write(_line(run))


def describe(run: dict) -> str:
    if run["status"] != "ok":
        return f"{run['source']} sem conferência ({run['reason']})"
    return (f"{run['source']} {run['online']} no ar, {run['unstable']} instáveis, {run['offline']} fora do ar, "
            f"{run['unverified']} não conferidos, {run['transitions']} trocas")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Confere as versões jogáveis listadas nos catálogos.")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary-file", help="arquivo de resumo; a linha é acrescentada ao fim")
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = []
    for source in load_json(cc.SOURCES_FILE):
        if source["status"] != "active" or source["kind"] != "ports" or (args.only and source["id"] not in args.only):
            continue
        snapshot = cc.load_snapshot(source["id"]) or {}
        run, status, transitions = check_source(source, stamp, load_status(source["id"]), set(snapshot))
        if not args.dry_run:
            store(run, status, transitions)
        lines.append(describe(run))
        print(describe(run), f"| {run['checked']} de {run['targets']} em {run['seconds']} s")
    if args.summary_file and lines:
        with open(args.summary_file, "a", encoding="utf-8") as out:
            out.write("\nSituação das versões jogáveis: " + "; ".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

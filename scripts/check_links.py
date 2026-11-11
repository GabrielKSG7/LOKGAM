#!/usr/bin/env python3
"""Confere os links dos ports e acrescenta o resultado em data/checks.jsonl.

Uso:
  python3 scripts/check_links.py                    confere e grava
  python3 scripts/check_links.py --dry-run          confere e só mostra
  python3 scripts/check_links.py --only halo-ce-web diablo-web

Cada passagem grava uma linha por port, todas com o mesmo `checked_at`.
Site fora do ar é dado, não erro: o script só sai com código 1 quando a própria
conferência falha (por exemplo, o robô sem rede).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

import requests

from validate import ROOT, load_json

USER_AGENT = "LOKGAM-conferencia/1.0 (+https://github.com/GabrielKSG7/LOKGAM)"
TIMEOUT = (10, 20)  # segundos para conectar e para cada leitura
MAX_BYTES = 256 * 1024
ATTEMPTS = 3
PAUSE_SECONDS = 4
WORKERS = 6

CHECKS_FILE = ROOT / "data" / "checks.jsonl"
STATE_LABELS = {
    "online": "no ar",
    "unstable": "instável",
    "offline": "fora do ar",
    "unverified": "não conferido",
}
# Motivos que significam "o robô não conseguiu chegar ao site". Se todas as
# conferências de uma passagem caírem aqui, o problema é a rede do robô.
NETWORK_REASONS = {"timeout", "dns_error", "connection_error", "tls_error"}
# Motivos em que insistir não muda a resposta.
FINAL_REASONS = {"ok", "bot_blocked", "not_found", "legal_block", "takedown_notice"}

CHALLENGE_MARKERS = ("just a moment...", "challenge-platform", "cf-chl-", "attention required! | cloudflare")
DNS_MARKERS = (
    "nameresolutionerror",
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "no address associated with hostname",
)
TAG_BLOCKS = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
TAGS = re.compile(r"<[^>]+>")
REMOVAL_SENTENCE = re.compile(
    r"\b(this|the) (game|site|website|page|project|port|demo|content|repository|repo)\b[^.]{0,80}"
    r"\b(was|were|is|are|has been|have been) (removed|taken down|disabled|no longer available|unavailable)",
    re.I,
)
RIGHTS_WORDS = re.compile(r"dmca|takedown|take-down|copyright|cease and desist|legal request", re.I)
SHORT_PAGE_CHARS = 4000


@dataclass
class Probe:
    """O que voltou de uma tentativa de abrir o link."""

    status: int | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str = ""
    error: str | None = None
    elapsed_ms: int | None = None
    final_url: str | None = None


@dataclass
class Verdict:
    state: str
    reason: str
    note: str = ""


def visible_text(html: str) -> str:
    text = TAGS.sub(" ", TAG_BLOCKS.sub(" ", html))
    return re.sub(r"\s+", " ", text).strip()


def is_bot_challenge(probe: Probe) -> bool:
    if probe.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    head = probe.body[:20000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


def has_takedown_notice(body: str) -> bool:
    """Página curta que diz que o jogo foi removido e cita direitos autorais."""
    text = visible_text(body)
    return len(text) <= SHORT_PAGE_CHARS and bool(REMOVAL_SENTENCE.search(text)) and bool(RIGHTS_WORDS.search(text))


def classify(probe: Probe) -> Verdict:
    """Traduz a resposta em estado (para a luz da capa) e motivo (para a análise)."""
    if probe.error == "timeout":
        return Verdict("unstable", "timeout", "O site não respondeu a tempo.")
    if probe.error == "dns_error":
        return Verdict("offline", "dns_error", "O endereço não existe mais (falha de DNS).")
    if probe.error == "tls_error":
        return Verdict("unstable", "tls_error", "Problema no certificado de segurança do site.")
    if probe.error == "redirect_loop":
        return Verdict("unstable", "other_http", "O site entrou em um ciclo de redirecionamentos.")
    if probe.error or probe.status is None:
        return Verdict("unstable", "connection_error", "Não foi possível conectar ao site.")

    status = probe.status
    if 200 <= status < 300:
        if is_bot_challenge(probe):
            return Verdict("unverified", "bot_blocked", "O site respondeu com um desafio contra robôs.")
        if has_takedown_notice(probe.body):
            return Verdict("unstable", "takedown_notice", "A página mostra um aviso de remoção. Conferir à mão.")
        return Verdict("online", "ok")
    if status in (401, 403, 429) or (status == 503 and is_bot_challenge(probe)):
        return Verdict("unverified", "bot_blocked", f"O site barrou o robô (HTTP {status}).")
    if status in (404, 410):
        return Verdict("offline", "not_found", f"A página não existe mais (HTTP {status}).")
    if status == 451:
        return Verdict("offline", "legal_block", "Indisponível por motivo legal (HTTP 451).")
    if 520 <= status <= 527 or status == 530:
        return Verdict("unstable", "server_error", f"A Cloudflare não conseguiu falar com o servidor do site (HTTP {status}).")
    if 500 <= status < 600:
        return Verdict("unstable", "server_error", f"Erro no servidor do site (HTTP {status}).")
    return Verdict("unstable", "other_http", f"Resposta inesperada (HTTP {status}).")


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
    )
    return session


def _error_kind(exc: Exception) -> str:
    text = repr(exc).lower()
    if isinstance(exc, requests.exceptions.Timeout) or "timed out" in text:
        return "timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        return "tls_error"
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return "redirect_loop"
    if any(marker in text for marker in DNS_MARKERS):
        return "dns_error"
    return "connection_error"


def probe(session: requests.Session, url: str, timeout: tuple[float, float] = TIMEOUT) -> Probe:
    """Abre o link uma vez e lê só o começo da página."""
    started = time.monotonic()
    try:
        with session.get(url, timeout=timeout, stream=True, allow_redirects=True) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
            body = b"".join(chunks)[:MAX_BYTES].decode(response.encoding or "utf-8", errors="replace")
            return Probe(
                status=response.status_code,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                final_url=response.url,
            )
    except requests.exceptions.RequestException as exc:
        return Probe(error=_error_kind(exc), elapsed_ms=round((time.monotonic() - started) * 1000))


def _host(url: str | None) -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def check_url(
    session: requests.Session,
    url: str,
    attempts: int = ATTEMPTS,
    pause: float = PAUSE_SECONDS,
    timeout: tuple[float, float] = TIMEOUT,
) -> tuple[Probe, Verdict]:
    """Confere um link, insistindo quando a falha pode ser passageira."""
    for attempt in range(1, attempts + 1):
        result = probe(session, url, timeout=timeout)
        verdict = classify(result)
        if verdict.reason in FINAL_REASONS or attempt == attempts:
            break
        time.sleep(pause)
    if verdict.state == "online" and result.final_url and _host(result.final_url) != _host(url):
        verdict.note = f"Redirecionou para {_host(result.final_url)}."
    return result, verdict


def monitored(ports: list[dict], only: list[str] | None = None) -> list[dict]:
    """Ports que têm link guardado: os aprovados e os que estão em análise."""
    chosen = [p for p in ports if p["links"]["play"] and p["curation"]["state"] in ("approved", "pending")]
    if only:
        unknown = sorted(set(only) - {p["id"] for p in chosen})
        if unknown:
            raise SystemExit(f"Fichas sem link para conferir: {', '.join(unknown)}")
        chosen = [p for p in chosen if p["id"] in only]
    return chosen


def run(
    ports: list[dict],
    stamp: str,
    session_factory: Callable[[], requests.Session] = new_session,
    **check_options,
) -> list[dict]:
    """Confere todos os ports em paralelo e devolve as linhas na ordem da base."""

    def one(port: dict) -> dict:
        with session_factory() as session:
            result, verdict = check_url(session, port["links"]["play"], **check_options)
        row = {
            "port_id": port["id"],
            "checked_at": stamp,
            "state": verdict.state,
            "reason": verdict.reason,
            "method": "link_checker",
            "http_status": result.status,
            "response_ms": result.elapsed_ms,
        }
        if verdict.note:
            row["note"] = verdict.note
        return row

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(one, ports))


def network_is_down(rows: list[dict]) -> bool:
    return len(rows) >= 2 and all(row["reason"] in NETWORK_REASONS for row in rows)


def summary_line(rows: list[dict], stamp: str) -> str:
    counts = Counter(row["state"] for row in rows)
    parts = [f"{counts[state]} {label}" for state, label in STATE_LABELS.items() if counts[state]]
    return f"Conferência de links de {stamp[:10]} {stamp[11:16]} UTC: {', '.join(parts)}"


def markdown_table(rows: list[dict], titles: Mapping[str, str]) -> str:
    lines = ["| Port | Estado | HTTP | Tempo | Observação |", "|---|---|---|---|---|"]
    for row in rows:
        status = row["http_status"] if row["http_status"] is not None else ""
        elapsed = f"{row['response_ms']} ms" if row["response_ms"] is not None else ""
        lines.append(
            f"| {titles[row['port_id']]} | {STATE_LABELS[row['state']]} | {status} | {elapsed} | {row.get('note', '')} |"
        )
    return "\n".join(lines)


def append_rows(rows: list[dict], path: Path = CHECKS_FILE) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Confere os links dos ports do LOKGAM.")
    parser.add_argument("--dry-run", action="store_true", help="confere e mostra, sem gravar")
    parser.add_argument("--only", nargs="+", metavar="ID", help="confere só estas fichas")
    parser.add_argument("--summary-file", type=Path, help="grava o resumo de uma linha neste arquivo")
    args = parser.parse_args(argv)

    ports = monitored(load_json(ROOT / "data" / "ports.json"), args.only)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = run(ports, stamp)
    titles = {p["id"]: p["title"] for p in ports}

    for row in rows:
        detail = f"HTTP {row['http_status']}" if row["http_status"] is not None else row["reason"]
        print(f"{STATE_LABELS[row['state']]:>14}  {row['port_id']}  ({detail})")

    if network_is_down(rows):
        print("Todas as conferências falharam por erro de rede: o robô parece estar sem internet. Nada foi gravado.")
        return 1

    line = summary_line(rows, stamp)
    print(line)
    if args.summary_file:
        args.summary_file.write_text(line + "\n", encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(f"### {line}\n\n{markdown_table(rows, titles)}\n")
    if args.dry_run:
        print("Simulação: nada foi gravado.")
    else:
        append_rows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Coleta os catálogos de ports e guarda um retrato de cada um: a camada bronze.

Para cada fonte ativa em data/sources.json o coletor baixa a lista, lê as entradas e grava:

    data/bronze/<fonte>/snapshot.jsonl   o retrato mais recente, uma entrada por linha
    data/bronze/<fonte>/changes.jsonl    o que entrou, saiu ou mudou desde o retrato anterior
    data/bronze/runs.jsonl               uma linha por fonte a cada execução, com medidas de qualidade

O retrato guarda só a identidade de cada entrada: título, domínio da versão jogável e dono do
repositório do código. O endereço completo e o texto original nunca são gravados. Do endereço
fica uma impressão digital (hash), que basta para saber se ele mudou.

Uso:
    python3 scripts/collect_catalogs.py [--only ID ...] [--dry-run] [--summary-file CAMINHO]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from jsonschema import Draft202012Validator

from validate import ROOT, load_json, load_jsonl

USER_AGENT = "LOKGAM-coleta/1.0 (+https://github.com/GabrielKSG7/LOKGAM)"
TIMEOUT = (10, 30)
MAX_BYTES = 8 * 1024 * 1024
SOURCES_FILE = ROOT / "data" / "sources.json"
BRONZE = ROOT / "data" / "bronze"
# Se a coleta trouxer menos que esta fração do retrato anterior, ela é tratada como defeituosa
# (download cortado, formato novo) e não substitui o que já existe.
SHRINK_LIMIT = 0.5
# Sites de código em que o primeiro trecho do caminho é o dono do repositório.
CODE_HOSTS = {"github.com", "gitlab.com", "codeberg.org", "gitea.com", "bitbucket.org"}
FIELDS = (
    "title", "section", "play_host", "play_fingerprint",
    "source_host", "source_owner", "source_fingerprint", "extra",
)


# --- Leitura de markdown ---------------------------------------------------------------------

_MD_LINK = re.compile(r'!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*<?([^\s<>)]+)>?(?:\s+"[^"]*")?\s*\)')
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_SEPARATOR = re.compile(r"^:?-+:?$")
_PIPE = re.compile(r"(?<!\\)\|")
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~])")


@dataclass
class Cell:
    text: str
    links: list[tuple[str, str]]  # (rótulo, endereço)


@dataclass
class Table:
    heading: str
    header: list[str]
    rows: list[list[Cell]]


def _plain(text: str) -> str:
    """O texto de um trecho de markdown, sem a marcação."""
    text = _MD_LINK.sub(lambda m: "" if m.group(0).startswith("!") else m.group(1), text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("`", "")
    return " ".join(_ESCAPED.sub(r"\1", text).split())


def _cell(raw: str) -> Cell:
    links = [(m.group(1).strip(), m.group(2)) for m in _MD_LINK.finditer(raw) if not m.group(0).startswith("!")]
    return Cell(_plain(raw), links)


def _split(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [part.strip() for part in _PIPE.split(line)]


def _is_separator(line: str) -> bool:
    cells = _split(line)
    return bool(cells) and all(_SEPARATOR.match(cell.replace(" ", "")) for cell in cells)


def markdown_tables(text: str) -> list[Table]:
    """Todas as tabelas do documento, cada uma com o título da seção em que está."""
    tables: list[Table] = []
    heading = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        found = _HEADING.match(lines[i])
        if found:
            heading = _plain(found.group(1))
        elif "|" in lines[i] and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            header = [_plain(part) for part in _split(lines[i])]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append([_cell(part) for part in _split(lines[i])])
                i += 1
            tables.append(Table(heading, header, rows))
            continue
        i += 1
    return tables


# --- Identidade de uma entrada ---------------------------------------------------------------

_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
_OWNER = re.compile(r"^[A-Za-z0-9._-]{1,60}$")


_OTHER_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:(?!\d|//)", re.I)


def _parts(address: str):
    address = address.strip()
    return urlsplit(address if "://" in address else "https://" + address)


def host_of(address: str) -> str | None:
    """O domínio de um endereço da web, em minúsculas e sem 'www.'. None se não houver um válido."""
    address = address.strip()
    if _OTHER_SCHEME.match(address) or ("://" in address and not address.lower().startswith(("http://", "https://"))):
        return None  # mailto:, javascript:, ftp:// e afins
    try:
        host = (_parts(address).hostname or "").lower().rstrip(".")
        host = host.encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        return None
    if host.startswith("www."):
        host = host[4:]
    return host if _HOST.match(host) else None


def fingerprint(address: str) -> str:
    """Impressão digital de um endereço: muda se o endereço mudar, e não permite refazê-lo."""
    parts = _parts(address)
    normal = f"{(parts.hostname or '').lower()}{parts.path.rstrip('/')}?{parts.query}"
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()[:12]


def repo_owner(address: str) -> str | None:
    """O dono do repositório, quando o endereço é de um site de código."""
    if host_of(address) not in CODE_HOSTS:
        return None
    pieces = [piece for piece in _parts(address).path.split("/") if piece]
    return pieces[0] if pieces and _OWNER.match(pieces[0]) else None


def clean_title(text: str) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", text).split())[:200]


def slug(title: str) -> str:
    """Chave legível de um título. Se letras se perdem na conversão (outro alfabeto), entra um hash."""
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:80].strip("-")
    lost = sum(ch.isalnum() for ch in title) - sum(ch.isalnum() for ch in plain)
    if lost > 0 or not base:
        digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:6]
        return f"{base}-{digest}" if base else f"t-{digest}"
    return base


def assign_keys(entries: list[dict]) -> int:
    """Dá a cada entrada uma chave única dentro da fonte. Devolve quantas precisaram de sufixo."""
    seen: Counter = Counter()
    for entry in entries:
        base = slug(entry["title"])
        seen[base] += 1
        entry["key"] = base if seen[base] == 1 else f"{base}~{seen[base]}"
    return sum(count - 1 for count in seen.values())


def new_entry(title: str, section: str | None = None, play: str | None = None,
              source: str | None = None, extra: dict | None = None) -> dict:
    return {
        "key": "",
        "title": title,
        "section": section or None,
        "play_host": host_of(play) if play else None,
        "play_fingerprint": fingerprint(play) if play else None,
        "source_host": host_of(source) if source else None,
        "source_owner": repo_owner(source) if source else None,
        "source_fingerprint": fingerprint(source) if source else None,
        "extra": extra or {},
    }


# --- Leitores de cada fonte ------------------------------------------------------------------

def parse_ultimate_catalog(text: str, addresses: list | None = None) -> tuple[list[dict], dict]:
    """Tabelas 'Game | Play | Source', uma por letra. ▶ marca a versão jogável e 📦 o código.

    Se receber a lista `addresses`, põe nela o endereço jogável de cada entrada, na mesma ordem.
    É o único caminho pelo qual um endereço sai daqui, e serve ao robô que confere os links.
    """
    quality: Counter = Counter()
    entries = []
    for table in markdown_tables(text):
        if not table.header or table.header[0].lower() not in ("game", "games", "title"):
            quality["tables_skipped"] += 1
            continue
        quality["tables"] += 1
        section = table.heading.split("·")[0].strip()[:24]
        for row in table.rows:
            quality["rows_seen"] += 1
            starred = "⭐" in row[0].text
            title = clean_title(row[0].text.replace("⭐", ""))
            if not title:
                quality["rows_without_title"] += 1
                continue
            play = source = None
            for label, address in (link for cell in row[1:] for link in cell.links):
                host = host_of(address)
                if host is None:
                    quality["bad_links"] += 1
                elif "📦" in label or (host in CODE_HOSTS and "▶" not in label):
                    if source is None:
                        source = address
                    else:
                        quality["extra_links"] += 1
                elif play is None:
                    play = address
                else:
                    quality["extra_links"] += 1
            if play is None and source is None:
                quality["rows_without_links"] += 1
            # A lista marca com estrela o que tem as duas coisas: serve para conferir a leitura.
            if starred != (play is not None and source is not None):
                quality["star_mismatch"] += 1
            entries.append(new_entry(title, section, play, source))
            if addresses is not None:
                addresses.append(play)
    declared = re.search(r"badge/games-(\d+)", text) or re.search(r"\b(\d{2,6})\s+games\b", text[:4000])
    if declared:
        quality["declared_rows"] = int(declared.group(1))
    return entries, dict(quality)


def parse_bottleship_compat(text: str, addresses: list | None = None) -> tuple[list[dict], dict]:
    """Tabelas 'Title | Status | GOG' da lista de compatibilidade do BottleShip."""
    quality: Counter = Counter()
    entries = []
    for table in markdown_tables(text):
        header = [name.lower() for name in table.header]
        if "title" not in header or "status" not in header:
            quality["tables_skipped"] += 1
            continue
        quality["tables"] += 1
        at_title, at_status = header.index("title"), header.index("status")
        at_gog = header.index("gog") if "gog" in header else None
        for row in table.rows:
            quality["rows_seen"] += 1
            if len(row) <= max(at_title, at_status) or not clean_title(row[at_title].text):
                quality["rows_without_title"] += 1
                continue
            extra = {"status": re.sub(r"[*†‡§]", "", row[at_status].text).strip().lower()[:60]}
            if at_gog is not None and at_gog < len(row):
                extra["gog"] = "yes" if row[at_gog].text.strip() else "no"
            entries.append(new_entry(clean_title(row[at_title].text), table.heading[:24], extra=extra))
            if addresses is not None:
                addresses.append(None)
    return entries, dict(quality)


# nome do leitor -> (função, versão). Mudar a versão faz a próxima coleta virar um retrato novo,
# sem registrar como mudança do catálogo o que é só mudança da leitura.
PARSERS = {
    "ultimate_catalog": (parse_ultimate_catalog, 1),
    "bottleship_compat": (parse_bottleship_compat, 2),
}


# --- Download --------------------------------------------------------------------------------

@dataclass
class Fetched:
    ok: bool
    origin: str | None = None
    http_status: int | None = None
    text: str = ""
    size: int | None = None
    sha256: str | None = None
    reason: str | None = None


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown, */*;q=0.5"})
    return session


def robots_allows(session, url: str, timeout=TIMEOUT) -> bool:
    """Se o robots.txt do site deixa este robô ler o endereço. Na dúvida, não deixa."""
    parts = urlsplit(url)
    try:
        answer = session.get(f"{parts.scheme}://{parts.netloc}/robots.txt", timeout=timeout)
    except requests.RequestException:
        return False
    if answer.status_code in (401, 403) or answer.status_code >= 500:
        return False
    if answer.status_code >= 400:
        return True
    rules = RobotFileParser()
    rules.parse(answer.text.splitlines())
    return rules.can_fetch(USER_AGENT, url)


def fetch(session, source: dict, timeout=TIMEOUT) -> Fetched:
    """Tenta os endereços da fonte em ordem e devolve o primeiro que responder com conteúdo."""
    last = Fetched(False, reason="no_urls")
    for url in source["urls"]:
        origin = host_of(url)
        if source.get("respect_robots", True) and not robots_allows(session, url, timeout):
            last = Fetched(False, origin, reason="robots")
            continue
        try:
            answer = session.get(url, timeout=timeout)
        except requests.RequestException:
            last = Fetched(False, origin, reason="network")
            continue
        if answer.status_code != 200:
            last = Fetched(False, origin, answer.status_code, reason="http_error")
            continue
        body = answer.content
        if not body.strip() or len(body) > MAX_BYTES:
            last = Fetched(False, origin, 200, size=len(body), reason="bad_size")
            continue
        return Fetched(True, origin, 200, body.decode("utf-8", errors="replace"), len(body), hashlib.sha256(body).hexdigest())
    return last


# --- Retrato, mudanças e registro da execução ------------------------------------------------

def diff(before: dict[str, dict], after: dict[str, dict]) -> list[dict]:
    """O que entrou, saiu ou mudou entre dois retratos, na ordem das chaves."""
    changes = []
    for key in sorted(after.keys() - before.keys()):
        changes.append({"change": "added", "key": key, "title": after[key]["title"], "entry": after[key], "fields": {}})
    for key in sorted(before.keys() - after.keys()):
        changes.append({"change": "removed", "key": key, "title": before[key]["title"], "entry": before[key], "fields": {}})
    for key in sorted(after.keys() & before.keys()):
        fields = {name: [before[key].get(name), after[key].get(name)] for name in FIELDS if before[key].get(name) != after[key].get(name)}
        if fields:
            changes.append({"change": "changed", "key": key, "title": after[key]["title"], "entry": None, "fields": fields})
    return changes


_entry_schema = None


def _valid(entry: dict) -> bool:
    global _entry_schema
    if _entry_schema is None:
        _entry_schema = Draft202012Validator(load_json(ROOT / "schema" / "bronze_entry.schema.json"))
    return _entry_schema.is_valid(entry)


def collect_source(source: dict, stamp: str, session, previous: dict[str, dict] | None, last_run: dict | None):
    """Coleta uma fonte. Devolve (registro da execução, retrato novo ou None, mudanças)."""
    parse, version = PARSERS[source["parser"]]
    run = {
        "run_at": stamp, "source": source["id"], "status": "failed", "reason": None, "origin": None,
        "http_status": None, "bytes": None, "sha256": None, "parser_version": version, "rows": None,
        "baseline": False, "added": 0, "removed": 0, "changed": 0, "quality": {},
    }
    got = fetch(session, source)
    run.update(origin=got.origin, http_status=got.http_status, bytes=got.size, sha256=got.sha256)
    if not got.ok:
        run["reason"] = got.reason
        return run, None, []

    same_reader = bool(last_run) and last_run.get("parser_version") == version
    if previous is not None and same_reader and last_run.get("sha256") == got.sha256:
        run.update(status="unchanged", rows=len(previous))
        return run, None, []

    entries, quality = parse(got.text)
    quality["key_collisions"] = assign_keys(entries)
    kept = [entry for entry in entries if _valid(entry)]
    quality["dropped"] = len(entries) - len(kept)
    run["quality"] = {name: count for name, count in sorted(quality.items()) if count}
    if not kept:
        run["reason"] = "parse_empty"
        return run, None, []
    if previous and len(kept) < SHRINK_LIMIT * len(previous):
        run["reason"] = "shrunk"
        return run, None, []

    after = {entry["key"]: entry for entry in kept}
    baseline = previous is None or not same_reader
    changes = [] if baseline else diff(previous, after)
    tally = Counter(change["change"] for change in changes)
    run.update(status="ok", rows=len(after), baseline=baseline,
               added=tally["added"], removed=tally["removed"], changed=tally["changed"])
    return run, after, changes


def _line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False) + "\n"


def load_snapshot(source_id: str, root: Path = BRONZE) -> dict[str, dict] | None:
    path = root / source_id / "snapshot.jsonl"
    return {row["key"]: row for row in load_jsonl(path)} if path.exists() else None


def last_good_run(runs: list[dict], source_id: str) -> dict | None:
    good = [run for run in runs if run["source"] == source_id and run["status"] in ("ok", "unchanged")]
    return good[-1] if good else None


def store(run: dict, snapshot: dict[str, dict] | None, changes: list[dict], root: Path = BRONZE) -> None:
    folder = root / run["source"]
    if snapshot is not None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "snapshot.jsonl").write_text("".join(_line(snapshot[key]) for key in sorted(snapshot)), encoding="utf-8")
    if changes:
        with (folder / "changes.jsonl").open("a", encoding="utf-8") as out:
            for change in changes:
                out.write(_line({"seen_at": run["run_at"], "source": run["source"], **change}))
    root.mkdir(parents=True, exist_ok=True)
    with (root / "runs.jsonl").open("a", encoding="utf-8") as out:
        out.write(_line(run))


def describe(run: dict) -> str:
    if run["status"] == "failed":
        return f"{run['source']} falhou ({run['reason']})"
    if run["status"] == "unchanged":
        return f"{run['source']} sem mudanças"
    if run["baseline"]:
        return f"{run['source']} {run['rows']} entradas (retrato inicial)"
    return f"{run['source']} {run['rows']} entradas (+{run['added']} −{run['removed']} ~{run['changed']})"


def summary_line(runs: list[dict], stamp: str) -> str:
    when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M")
    return f"Coleta de catálogos de {when} UTC: " + ("; ".join(describe(run) for run in runs) or "nenhuma fonte ativa")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coleta os catálogos de ports (camada bronze).")
    parser.add_argument("--only", nargs="*", help="ids das fontes a coletar")
    parser.add_argument("--dry-run", action="store_true", help="não grava nada")
    parser.add_argument("--summary-file", help="onde gravar a linha de resumo")
    args = parser.parse_args(argv)

    sources = [s for s in load_json(SOURCES_FILE) if s["status"] == "active" and (not args.only or s["id"] in args.only)]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    known = load_jsonl(BRONZE / "runs.jsonl") if (BRONZE / "runs.jsonl").exists() else []
    session = new_session()
    runs = []
    for source in sources:
        run, snapshot, changes = collect_source(source, stamp, session, load_snapshot(source["id"]), last_good_run(known, source["id"]))
        runs.append(run)
        if not args.dry_run:
            store(run, snapshot, changes)
        print(describe(run), "| qualidade:", run["quality"] or "-")
    line = summary_line(runs, stamp)
    if args.summary_file:
        Path(args.summary_file).write_text(line + "\n", encoding="utf-8")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

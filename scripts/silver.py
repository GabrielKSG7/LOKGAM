#!/usr/bin/env python3
"""Camada prata: transforma entradas de catálogo em ports e jogos.

Entra o que a coleta guardou (data/bronze), as fichas curadas (data/ports.json) e a tabela de
referência de jogos de console (data/reference). Sai, em data/silver:

    ports.jsonl   um port por linha: entradas que apontam para a mesma versão jogável viram uma só,
                  ligadas à ficha curada quando existe, com a data em que a coleta as viu
    games.jsonl   um jogo por linha: quantos ports as listas trazem, plataformas e compatibilidade

Tudo aqui é função dos arquivos do repositório: rodar duas vezes dá o mesmo resultado.

Uso: python3 scripts/silver.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict

from collect_catalogs import fingerprint, host_of
from metrics import is_shared_hosting
from validate import ROOT, load_bronze, load_json, load_sources

SILVER = ROOT / "data" / "silver"
REFERENCE_FILE = ROOT / "data" / "reference" / "console_games.json"

# Grafias diferentes do mesmo nome. Aplicadas ao título em minúsculas.
ALIASES = (
    (re.compile(r"\bgta\b"), "grand theft auto"),
    (re.compile(r"^ctr:\s*"), ""),
)
ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9"}
# Títulos que não entram em nenhuma lista pública do site.
_ADULT = re.compile(r"\b(sex|hentai|porn\w*|nsfw|genital|penthouse|beat banger)\b", re.I)
_SENSITIVE = re.compile(r"\b(hitler|stalin|epstein|al-qa'?eda|hussein|kim jong)\b", re.I)


def split_title(title: str) -> tuple[str, str | None]:
    """Separa o nome do jogo do que a lista põe entre parênteses no fim: (2), (2005), (nome do port)."""
    base, groups = title.strip(), []
    while base.endswith(")"):
        depth, start = 0, None
        for i in range(len(base) - 1, -1, -1):
            depth += (base[i] == ")") - (base[i] == "(")
            if depth == 0:
                start = i
                break
        if not start:
            break
        groups.insert(0, base[start + 1:-1].strip())
        base = base[:start].rstrip()
    labels = [group for group in groups if not re.fullmatch(r"\d{1,4}", group)]
    return base, (labels[-1] if labels else None)


def game_id(title: str) -> str:
    """Chave de um jogo: o nome sem parênteses finais, sem pontuação e com as grafias niveladas."""
    base = split_title(title)[0].lower().replace("’", "'")
    for pattern, replacement in ALIASES:
        base = pattern.sub(replacement, base)
    plain = unicodedata.normalize("NFKD", base.replace("&", " and ")).encode("ascii", "ignore").decode("ascii")
    tokens = [ROMAN.get(token, token) for token in re.findall(r"[a-z0-9]+", plain.replace("'", ""))]
    slug = "-".join(tokens)[:80].strip("-")
    lost = sum(ch.isalnum() for ch in base) - sum(ch.isalnum() for ch in plain)
    if lost > 0 or not slug:
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:6]
        return f"{slug}-{digest}" if slug else f"t-{digest}"
    return slug


def flags_of(title: str) -> list[str]:
    return [name for name, pattern in (("adult", _ADULT), ("sensitive", _SENSITIVE)) if pattern.search(title)]


def _hosting(host: str | None) -> str:
    return "none" if not host else "shared" if is_shared_hosting(host) else "own"


def _timeline(source_id: str, bronze: dict) -> tuple[str | None, dict, dict, dict]:
    """Do registro da coleta: data do primeiro retrato, chegadas, saídas e trocas de domínio por chave."""
    good = [run["run_at"] for run in bronze["runs"] if run["source"] == source_id and run["status"] == "ok"]
    added, removed, moves = {}, {}, defaultdict(list)
    for change in bronze["changes"].get(source_id, []):
        key, at = change["key"], change["seen_at"]
        if change["change"] == "added":
            added.setdefault(key, at)
            removed.pop(key, None)
        elif change["change"] == "removed":
            removed[key] = (at, change["entry"])
        elif "play_host" in change["fields"]:
            before, after = change["fields"]["play_host"]
            moves[key].append({"at": at, "from": before, "to": after})
    return (min(good) if good else None), added, removed, moves


def build_silver(sources: list[dict], bronze: dict, fichas: list[dict], reference: list[dict]) -> tuple[list[dict], list[dict]]:
    order = {source["id"]: i for i, source in enumerate(sources)}
    kinds = {source["id"]: source["kind"] for source in sources}

    # 1. Entradas de catálogo: as do retrato atual e as que a coleta viu sair.
    listings = []
    for source_id in sorted(bronze["snapshots"], key=lambda name: order.get(name, 99)):
        if kinds.get(source_id) != "ports":
            continue
        baseline, added, removed, moves = _timeline(source_id, bronze)
        current = {entry["key"]: entry for entry in bronze["snapshots"][source_id]}
        gone = {key: (at, entry) for key, (at, entry) in removed.items() if key not in current}
        for key, entry in list(current.items()) + [(key, entry) for key, (_, entry) in gone.items()]:
            listings.append({
                "ref": f"{source_id}:{key}", "entry": entry, "listed": key in current,
                "removed_at": gone[key][0] if key in gone else None,
                "first_seen": added.get(key, baseline), "basis": "added" if key in added else "baseline",
                "moves": moves.get(key, []),
            })

    # 2. Ports: entradas com o mesmo endereço jogável são a mesma versão.
    groups: dict[str, list[dict]] = defaultdict(list)
    for listing in listings:
        groups[listing["entry"]["play_fingerprint"] or listing["ref"]].append(listing)

    # 3. Fichas curadas: cada uma procura o seu port, do indício mais forte para o mais fraco.
    linked: dict[str, tuple[set, str]] = {}
    rank = {"play": 0, "host": 1, "source": 2}

    def link(members: list[dict], ficha: dict, how: str) -> None:
        for group_key, group in groups.items():
            if any(m in group for m in members):
                ids, best = linked.get(group_key, (set(), how))
                linked[group_key] = (ids | {ficha["id"]}, min(best, how, key=rank.get))

    for ficha in fichas:
        gid, play, source = game_id(ficha["title"]), ficha["links"].get("play"), ficha["links"].get("source")
        same_address = [m for m in listings if play and m["entry"]["play_fingerprint"] == fingerprint(play)]
        same_host = [m for m in listings if play and m["entry"]["play_host"] == host_of(play) and game_id(m["entry"]["title"]) == gid]
        same_repo = [m for m in listings if source and m["entry"]["source_fingerprint"] == fingerprint(source)]
        exact = [m for m in same_address if game_id(m["entry"]["title"]) == gid]
        if exact:
            link(exact, ficha, "play")
        elif same_host:
            link(same_host, ficha, "host")
        elif len(same_address) == 1:
            # Endereço igual com nome diferente só vale se for o único: uma página que abre vários
            # jogos aparece na lista uma vez para cada um.
            link(same_address, ficha, "play")
        elif same_repo:
            link(same_repo, ficha, "source")

    ports = []
    for group_key, members in groups.items():
        first = members[0]
        entry = first["entry"]
        ficha_ids, how = linked.get(group_key, (set(), None))
        earliest = min(members, key=lambda m: (m["first_seen"] or "", m["ref"]))
        listed = any(m["listed"] for m in members)
        ports.append({
            "id": first["ref"],
            "game_id": game_id(entry["title"]),
            "title": entry["title"],
            "variant": split_title(entry["title"])[1],
            "listings": [m["ref"] for m in members],
            "play_host": entry["play_host"],
            "hosting": _hosting(entry["play_host"]),
            "source_host": entry["source_host"],
            "source_owner": entry["source_owner"],
            "ficha_ids": sorted(ficha_ids),
            "ficha_match": how,
            "first_seen": earliest["first_seen"],
            "first_seen_basis": earliest["basis"],
            "listed": listed,
            "removed_at": None if listed else max(m["removed_at"] for m in members),
            "moves": sorted((move for m in members for move in m["moves"]), key=lambda move: move["at"]),
            "flags": flags_of(entry["title"]),
        })
    ports.sort(key=lambda port: port["id"])

    # 4. Jogos: os das listas, os das fichas e os das fontes de compatibilidade.
    known = {game_id(row["title"]): row["platform"] for row in reference}
    games: dict[str, dict] = {}

    def game(gid: str, title: str) -> dict:
        return games.setdefault(gid, {
            "id": gid, "title": split_title(title)[0], "ports": 0, "listed_ports": 0, "playable_ports": 0,
            "sources": set(), "ficha_ids": set(), "platforms": [], "platforms_basis": None, "origin": None,
            "console": None, "compat": {}, "flags": flags_of(title),
        })

    for port in ports:
        row = game(port["game_id"], port["title"])
        row["ports"] += 1
        row["listed_ports"] += port["listed"]
        row["playable_ports"] += bool(port["listed"] and port["play_host"])
        row["sources"].update(ref.split(":")[0] for ref in port["listings"])
    for ficha in fichas:
        row = game(game_id(ficha["title"]), ficha["title"])
        if not row["ficha_ids"]:
            row["title"] = split_title(ficha["title"])[0]  # o nome da ficha é o revisado
        row["ficha_ids"].add(ficha["id"])
        row["platforms"] += [name for name in ficha["game"]["platforms"] if name not in row["platforms"]]
        row["platforms_basis"] = "ficha"
    for source_id in sorted(bronze["snapshots"]):
        if kinds.get(source_id) == "compatibility":
            for entry in bronze["snapshots"][source_id]:
                game(game_id(entry["title"]), entry["title"])["compat"][source_id] = entry["extra"].get("status", "listed")
    for gid, row in games.items():
        if not row["platforms"] and gid in known:
            row["platforms"], row["platforms_basis"] = [known[gid]], "reference"
        # Onde o jogo nasceu: a tabela de referência manda; sem ela, a primeira plataforma da ficha.
        row["origin"] = known.get(gid) or (row["platforms"][0] if row["platforms"] else None)
        row["console"] = None if row["origin"] is None else row["origin"] != "PC"
        row["sources"], row["ficha_ids"] = sorted(row["sources"]), sorted(row["ficha_ids"])
    return ports, [games[gid] for gid in sorted(games)]


def load_reference() -> list[dict]:
    return load_json(REFERENCE_FILE) if REFERENCE_FILE.exists() else []


def render(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def current() -> tuple[str, str]:
    """O texto que os dois arquivos da camada devem ter, dado o que está no repositório."""
    ports, games = build_silver(load_sources(), load_bronze(), load_json(ROOT / "data" / "ports.json"), load_reference())
    return render(ports), render(games)


def main() -> int:
    ports, games = current()
    SILVER.mkdir(parents=True, exist_ok=True)
    (SILVER / "ports.jsonl").write_text(ports, encoding="utf-8")
    (SILVER / "games.jsonl").write_text(games, encoding="utf-8")
    print(f"Camada prata: {ports.count(chr(10))} ports, {games.count(chr(10))} jogos")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Camada ouro: os modelos dbt, rodados sobre uma pasta de dados de exemplo.

A história do exemplo é escrita aqui de forma independente (estado de cada entrada em cada
conferência), e os arquivos da bronze são gerados a partir dela. Assim o teste compara o que o
dbt refaz com uma resposta que não saiu do dbt.
"""
import json
import shutil

import pytest

import gold

T = ["2026-11-12T01:00:00Z", "2026-11-13T01:00:00Z", "2026-11-14T01:00:00Z", "2026-11-15T01:00:00Z"]
BASELINE = "2026-11-11T20:00:00Z"
ADD_G = "2026-11-13T12:00:00Z"     # g entra no catálogo entre a 2ª e a 3ª conferência
REMOVE_D = "2026-11-14T12:00:00Z"  # d sai do catálogo entre a 3ª e a 4ª, ainda fora do ar

HOSTS = {"a": "espelho.example", "b": "espelho.example", "c": "espelho.example", "d": "outro.example",
         "e": "solo.example", "f": None, "g": "novo.example"}
# Estado de cada entrada em cada conferência; None = ainda não conferida ou já fora da lista.
STATES = {
    "a": ["online", "offline", "online", "online"],
    "b": ["online", "offline", "online", "online"],
    "c": ["online", "offline", "offline", "offline"],
    "d": ["offline", "offline", "offline", None],
    "e": ["online", "unstable", "online", "offline"],
    "g": [None, None, "online", "online"],
}


def write_bronze(root):
    folder = root / "bronze" / "lista"
    folder.mkdir(parents=True)

    def lines(path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    entry = lambda key: {"key": key, "title": key.upper(), "section": None, "play_host": HOSTS[key], "play_fingerprint": None,
                         "source_host": None, "source_owner": None, "source_fingerprint": None, "extra": {}}
    lines(folder / "snapshot.jsonl", [entry(k) for k in "abcefg"])
    lines(folder / "changes.jsonl", [
        {"seen_at": ADD_G, "source": "lista", "change": "added", "key": "g", "title": "G", "entry": entry("g"), "fields": {}},
        {"seen_at": REMOVE_D, "source": "lista", "change": "removed", "key": "d", "title": "D", "entry": entry("d"), "fields": {}},
    ])
    lines(root / "bronze" / "runs.jsonl", [
        {"run_at": BASELINE, "source": "lista", "status": "ok", "rows": 6, "added": 0, "removed": 0, "changed": 0, "baseline": True},
        {"run_at": ADD_G, "source": "lista", "status": "ok", "rows": 7, "added": 1, "removed": 0, "changed": 0, "baseline": False},
        {"run_at": REMOVE_D, "source": "lista", "status": "ok", "rows": 6, "added": 0, "removed": 1, "changed": 0, "baseline": False},
    ])
    # Trocas, situação atual e contagens do robô, todas derivadas de STATES.
    changes, runs, current = [], [], {}
    for i, at in enumerate(T):
        counts = {s: 0 for s in ("online", "unstable", "offline", "unverified")}
        for key, history in STATES.items():
            now, before = history[i], history[i - 1] if i else None
            if now is None and before is not None:
                changes.append({"source": "lista", "at": at, "key": key, "from": before, "to": "unlisted", "reason": None, "http_status": None})
                current.pop(key)
            if now is None:
                continue
            counts[now] += 1
            if before is None:
                current[key] = {"key": key, "state": now, "reason": "ok", "http_status": 200, "since": at}
            elif before != now:
                changes.append({"source": "lista", "at": at, "key": key, "from": before, "to": now, "reason": "ok", "http_status": 200})
                current[key] = {**current[key], "state": now, "since": at}
        runs.append({"run_at": at, "source": "lista", "status": "ok", "reason": None, "targets": sum(counts.values()), "checked": sum(counts.values()),
                     **counts, "transitions": 0, "seconds": 1})
    lines(folder / "status_changes.jsonl", changes)
    lines(folder / "status.jsonl", [current[k] for k in sorted(current)])
    lines(root / "bronze" / "status_runs.jsonl", runs)


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    if shutil.which("dbt") is None:
        pytest.skip("dbt não instalado")
    root = tmp_path_factory.mktemp("dados")
    write_bronze(root)
    database = root / "gold.duckdb"
    gold.run_dbt(data_dir=root, database=database, target=root / "target")  # inclui os testes de dados do dbt
    return gold.read_tables(database)


def by(rows, *fields):
    return {tuple(row[f] for f in fields) if len(fields) > 1 else row[fields[0]]: row for row in rows}


def test_daily_status_is_rebuilt_from_the_changes(tables):
    daily = by(tables["gold_daily_status"], "run_at")
    for i, at in enumerate(T):
        states = [h[i] for h in STATES.values() if h[i]]
        row = daily[at]
        assert (row["checked"], row["online"], row["unstable"], row["offline"]) == (
            len(states), states.count("online"), states.count("unstable"), states.count("offline"))
    assert (daily[T[1]]["offline_collective"], daily[T[1]]["offline_isolated"]) == (3, 1)
    assert (daily[T[3]]["offline_collective"], daily[T[3]]["offline_isolated"]) == (1, 1)


def test_outage_episodes(tables):
    outages = by(tables["gold_outages"], "key", "started_at")
    a = outages[("a", T[1])]
    assert (a["started_basis"], a["ended_at"], a["end_reason"], a["hours_down"], a["collective"], a["collective_size"]) == (
        "observed", T[2], "recovered", 24.0, True, 3)
    c = outages[("c", T[1])]
    assert (c["ended_at"], c["end_reason"], c["hours_down"], c["collective"]) == (None, None, None, True)
    d = outages[("d", T[0])]
    assert (d["started_basis"], d["ended_at"], d["end_reason"], d["collective"]) == ("before_first_check", T[3], "removed", False)
    e = outages[("e", T[3])]
    assert (e["started_basis"], e["collective"], e["play_host"]) == ("observed", False, "solo.example")
    assert len(outages) == 5 and not any(key == "f" for key, _ in outages)  # f nunca teve versão jogável


def test_collective_outages_and_findings(tables):
    [event] = tables["gold_collective_outages"]
    assert (event["play_host"], event["started_at"], event["ports"], event["recovered"], event["still_down"], event["last_recovered_at"]) == (
        "espelho.example", T[1], 3, 2, 1, T[2])
    [f] = tables["gold_findings"]
    assert (f["checks"], f["days_observed"], f["observed_outages"], f["observed_collective"], f["observed_recovered"]) == (4, 3.0, 4, 3, 2)
    assert (f["median_hours_down"], f["down_since_first_check"], f["collective_events"]) == (24.0, 0, 1)
    assert (f["added_since_baseline"], f["removed_since_baseline"], f["checked_now"], f["offline_now"]) == (1, 1, 5, 2)


def test_export_is_one_record_per_line(tables):
    text = gold.render(tables["gold_collective_outages"])
    assert text.startswith("[\n") and text.endswith("\n]\n") and json.loads(text) == tables["gold_collective_outages"]
    assert gold.render([]) == "[]\n"


def test_repo_gold_files_match_the_models():
    exported = {table: json.loads((gold.GOLD / f"{table.removeprefix('gold_')}.json").read_text(encoding="utf-8")) for table in gold.TABLES}
    assert exported["gold_findings"] and all("://" not in json.dumps(rows) for rows in exported.values())

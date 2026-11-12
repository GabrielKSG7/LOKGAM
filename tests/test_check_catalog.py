"""Conferência diária das versões jogáveis dos catálogos."""
from types import SimpleNamespace

import check_catalog as ck
import collect_catalogs as cc
import silver
import validate
from metrics import base_summary
from test_collect import CATALOG, SOURCE, FakeSession

T0, T1 = "2026-11-12T04:43:00Z", "2026-11-13T04:43:00Z"


def checker(answers, default=("online", "ok", 200)):
    """Finge o robô: decide a resposta pelo domínio do endereço."""
    seen = []

    def check(session, url):
        seen.append(url)
        state, reason, status = answers.get(cc.host_of(url), default)
        return SimpleNamespace(status=status), SimpleNamespace(state=state, reason=reason)

    return check, seen


def run(answers=None, previous=None, stamp=T0, text=CATALOG, keys=None, default=("online", "ok", 200)):
    check, seen = checker(answers or {}, default)
    session = FakeSession({SOURCE["urls"][0]: (200, text)})
    _, snapshot, _ = cc.collect_source(SOURCE, stamp, session, None, None)
    out = ck.check_source({**SOURCE, "kind": "ports"}, stamp, previous or {}, set(snapshot) if keys is None else keys,
                          session=session, check=check, session_factory=lambda: None, pause=0)
    return out, seen


def test_addresses_stay_in_memory_and_only_the_state_is_kept():
    (result, status, transitions), seen = run({"outro.example": ("offline", "not_found", 404)})
    assert len(seen) == 6 and all(url.startswith("https://") for url in seen)
    assert (result["status"], result["targets"], result["checked"], result["online"], result["offline"], result["transitions"]) == ("ok", 6, 6, 5, 1, 0)
    assert transitions == [] and status["animal-crossing~2"] == {"key": "animal-crossing~2", "state": "offline", "reason": "not_found", "http_status": 404, "since": T0}
    assert "b" not in status  # entrada sem versão jogável não é conferida
    assert "://" not in "".join(ck._line(row) for row in status.values())


def test_a_change_of_state_is_recorded_once_and_since_follows_it():
    (_, first, _), _ = run()
    (result, status, transitions), _ = run({"outro.example": ("offline", "dns_error", None)}, previous=first, stamp=T1)
    assert transitions == [{"at": T1, "key": "animal-crossing~2", "from": "online", "to": "offline", "reason": "dns_error", "http_status": None}]
    assert status["animal-crossing~2"]["since"] == T1 and status["alice"]["since"] == T0 and result["transitions"] == 1
    (_, again, none), _ = run({"outro.example": ("offline", "dns_error", None)}, previous=status, stamp="2026-11-14T04:43:00Z")
    assert none == [] and again["animal-crossing~2"]["since"] == T1


def test_only_entries_of_the_snapshot_are_checked_and_stale_ones_leave():
    (_, first, _), _ = run()
    (result, status, _), seen = run(previous=first, stamp=T1, keys={"alice", "amazing-alex"})
    assert sorted(status) == ["alice", "amazing-alex"] and len(seen) == 2 and result["targets"] == 2


def test_a_dead_network_or_an_unreadable_catalog_changes_nothing():
    (result, status, transitions), _ = run(default=("unstable", "timeout", None))
    assert (result["status"], result["reason"], status, transitions) == ("skipped", "network_down", None, [])
    out = ck.check_source({**SOURCE, "kind": "ports"}, T0, {}, {"alice"}, session=FakeSession({}))
    assert (out[0]["status"], out[0]["reason"], out[1]) == ("failed", "network", None)


def test_time_budget_keeps_the_previous_state_of_what_was_not_reached():
    (_, first, _), _ = run({"outro.example": ("offline", "not_found", 404)})
    check, seen = checker({})
    results = ck.check_targets({"a": "https://a.example/"}, check=check, session_factory=lambda: None, budget=-1)
    status, transitions = ck.apply(first, results, set(first), T1)
    assert (results, seen, transitions) == ({}, [], []) and status == first


def test_each_host_is_visited_by_one_worker_in_order():
    order = []

    def check(session, url):
        order.append(url)
        return SimpleNamespace(status=200), SimpleNamespace(state="online", reason="ok")

    targets = {f"k{i}": f"https://mesmo.example/{i}" for i in range(5)}
    ck.check_targets(targets, check=check, session_factory=lambda: None, pause=0)
    assert order == [f"https://mesmo.example/{i}" for i in range(5)]


def test_store_and_validate(tmp_path):
    session = FakeSession({SOURCE["urls"][0]: (200, CATALOG)})
    run_row, snapshot, _ = cc.collect_source(SOURCE, T0, session, None, None)
    cc.store(run_row, snapshot, [], tmp_path)
    (first_run, first, _), _ = run()
    ck.store(first_run, first, [], tmp_path)
    (second_run, second, transitions), _ = run({"outro.example": ("offline", "not_found", 404)}, previous=ck.load_status("lista", tmp_path), stamp=T1)
    ck.store(second_run, second, transitions, tmp_path)
    bronze = validate.load_bronze(tmp_path)
    assert [r["status"] for r in bronze["status_runs"]] == ["ok", "ok"] and len(bronze["status"]["lista"]) == 6
    assert [(c["key"], c["from"], c["to"], c["source"]) for c in bronze["status_changes"]["lista"]] == [("animal-crossing~2", "online", "offline", "lista")]
    for rows, name, key in ((bronze["status_runs"], "bronze_status_run", "source"), (bronze["status"]["lista"], "bronze_status", "key"), (bronze["status_changes"]["lista"], "bronze_status_change", "key")):
        assert validate.schema_errors(rows, f"{name}.schema.json", key) == []
    assert validate.pipeline_errors([{"id": "lista", "catalog_id": "c", "status": "active", "parser": "ultimate_catalog", "urls": ["https://a.example/"]}], [{"id": "c"}], bronze) == []
    # A prata leva a situação para o port, e o resumo conta por situação.
    bronze["runs"] = [{"source": "lista", "run_at": T0, "status": "ok"}]
    ports, games = silver.build_silver([{"id": "lista", "kind": "ports"}], bronze, [], [])
    by_id = {p["id"]: p for p in ports}
    assert (by_id["lista:animal-crossing~2"]["state"], by_id["lista:animal-crossing~2"]["state_since"], by_id["lista:b"]["state"]) == ("offline", T1, None)
    out = base_summary(ports, games, [], checked_at=T1)
    assert (out["states"], out["checked"], out["checked_at"]) == ({"online": 5, "unstable": 0, "offline": 1, "unverified": 0}, 6, T1)

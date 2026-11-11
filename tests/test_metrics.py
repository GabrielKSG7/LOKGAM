"""Métricas do observatório sobre bases pequenas, montadas à mão."""
from __future__ import annotations

from metrics import MIN_SAMPLES, actors, availability, by_port, composition, events_by_month, latest


def port(pid, state="approved", technique="source_port", play="https://exemplo.test/jogo"):
    return {
        "id": pid,
        "title": pid.title(),
        "port": {"name": f"Port {pid}", "technique": technique},
        "links": {"play": play},
        "curation": {"state": state},
    }


def check(pid, when, state, method="link_checker"):
    return {"port_id": pid, "checked_at": when, "state": state, "method": method}


def test_latest_prefers_the_last_line_on_a_tie():
    rows = by_port([check("a", "2026-11-10", "online"), check("a", "2026-11-10", "unstable")])["a"]
    assert latest(rows)["state"] == "unstable"


def test_date_without_time_sorts_before_times_of_the_same_day():
    rows = by_port([check("a", "2026-11-10T08:00:00Z", "offline"), check("a", "2026-11-10", "online")])["a"]
    assert [row["state"] for row in rows] == ["online", "offline"]


def test_latest_observed_skips_checks_where_the_robot_was_blocked():
    rows = by_port(
        [check("a", "2026-11-10T00:00:00Z", "unstable"), check("a", "2026-11-10T06:00:00Z", "unverified")]
    )["a"]
    assert latest(rows)["state"] == "unverified"
    assert latest(rows, observed_only=True)["state"] == "unstable"
    assert latest([check("a", "2026-11-10", "unverified")], observed_only=True) is None


def test_availability_waits_for_enough_samples():
    checks = [check("a", f"2026-11-1{day}T00:00:00Z", "online") for day in range(MIN_SAMPLES - 1)]
    (row,) = availability([port("a")], checks)
    assert row["observed"] == MIN_SAMPLES - 1 and row["pct"] is None


def test_availability_ignores_blocked_checks_in_the_percentage():
    checks = (
        [check("a", f"2026-11-01T{hour:02d}:00:00Z", "online") for hour in range(6)]
        + [check("a", f"2026-11-02T{hour:02d}:00:00Z", "unverified") for hour in range(5)]
        + [check("a", "2026-11-03T00:00:00Z", "unstable"), check("a", "2026-11-03T06:00:00Z", "offline")]
    )
    (row,) = availability([port("a")], checks)
    assert (row["checks"], row["observed"], row["blocked"]) == (13, 8, 5)
    assert row["pct"] == 0.75
    assert row["first_check"] == "2026-11-01T00:00:00Z"
    assert row["seen"]["state"] == "offline" and row["last"]["state"] == "offline"


def test_availability_covers_only_ports_with_a_link():
    ports = [port("a"), port("b", state="pending"), port("c", state="rejected", play=None)]
    rows = availability(ports, [check("a", "2026-11-10", "online")])
    assert [row["id"] for row in rows] == ["a", "b"]
    assert rows[1]["checks"] == 0 and rows[1]["seen"] is None and rows[1]["strip"] == []


def event(pid, date, kind, actor=None):
    return {"port_id": pid, "date": date, "kind": kind, "actor": actor}


def test_events_by_month_fills_empty_months_and_reaches_the_last_check():
    events = [
        event("a", "2025-12", "dmca_notice", "Take-Two"),
        event("b", "2026-02-10", "outage"),
        event("b", "2026-02-20", "removal"),
        event("c", "2026-01-05", "launch"),
    ]
    rows = events_by_month(events, until="2026-03-15T06:17:00Z")
    assert [row["month"] for row in rows] == ["2025-12", "2026-01", "2026-02", "2026-03"]
    assert [(row["rights_actions"], row["outages"]) for row in rows] == [(1, 0), (0, 0), (1, 1), (0, 0)]


def test_events_by_month_with_nothing_to_count():
    assert events_by_month([event("a", "2026-01-05", "launch")]) == []


def test_actors_counts_only_rights_actions_and_puts_unknown_last():
    ports = [port("a"), port("b"), port("c")]
    events = [
        event("a", "2026-10-01", "dmca_notice", "Activision"),
        event("b", "2026-10-02", "dmca_notice", "Activision"),
        event("c", "2026-10-03", "removal", None),
        event("c", "2026-10-04", "dmca_notice", "Sega"),
        event("a", "2026-10-05", "outage", "Cloudflare"),
    ]
    rows = actors(events, ports)
    assert [(row["actor"], row["count"]) for row in rows] == [("Activision", 2), ("Sega", 1), ("", 1)]
    assert rows[0]["ports"] == ["A", "B"]


def test_composition_counts_by_technique_and_state():
    ports = [
        port("a", technique="decompilation"),
        port("b", state="rejected", technique="decompilation", play=None),
        port("c", technique="emulation"),
        port("d", state="rejected", technique="unknown", play=None),
        port("e", state="pending", technique="unknown"),
    ]
    rows = composition(ports)
    assert [row["technique"] for row in rows] == ["decompilation", "emulation", "unknown"]
    assert rows[0] == {"technique": "decompilation", "approved": 1, "pending": 0, "rejected": 1, "total": 2}

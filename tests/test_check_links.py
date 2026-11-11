"""Classificação das respostas e conferência de ponta a ponta contra um servidor local."""
from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

import check_links
from check_links import Probe, check_url, classify, has_takedown_notice, network_is_down, run, summary_line

GAME_PAGE = "<html><head><title>Jogo</title></head><body><canvas id='tela'></canvas></body></html>"
CHALLENGE_PAGE = "<html><head><title>Just a moment...</title></head><body><script src='/cdn-cgi/challenge-platform/x.js'></script></body></html>"
REMOVAL_PAGE = "<html><body><p>This game was removed from the website due to a DMCA takedown request from Take-Two.</p></body></html>"


@pytest.mark.parametrize(
    "probe, state, reason",
    [
        (Probe(status=200, body=GAME_PAGE), "online", "ok"),
        (Probe(status=204), "online", "ok"),
        (Probe(status=200, body=CHALLENGE_PAGE), "unverified", "bot_blocked"),
        (Probe(status=200, body=REMOVAL_PAGE), "unstable", "takedown_notice"),
        (Probe(status=401), "unverified", "bot_blocked"),
        (Probe(status=403, body="Access denied"), "unverified", "bot_blocked"),
        (Probe(status=403, headers={"cf-mitigated": "challenge"}), "unverified", "bot_blocked"),
        (Probe(status=429), "unverified", "bot_blocked"),
        (Probe(status=503, body=CHALLENGE_PAGE), "unverified", "bot_blocked"),
        (Probe(status=503, body="Service Unavailable"), "unstable", "server_error"),
        (Probe(status=404), "offline", "not_found"),
        (Probe(status=410), "offline", "not_found"),
        (Probe(status=451), "offline", "legal_block"),
        (Probe(status=500), "unstable", "server_error"),
        (Probe(status=522), "unstable", "server_error"),
        (Probe(status=418), "unstable", "other_http"),
        (Probe(error="timeout"), "unstable", "timeout"),
        (Probe(error="dns_error"), "offline", "dns_error"),
        (Probe(error="tls_error"), "unstable", "tls_error"),
        (Probe(error="connection_error"), "unstable", "connection_error"),
        (Probe(error="redirect_loop"), "unstable", "other_http"),
    ],
)
def test_classify(probe, state, reason):
    verdict = classify(probe)
    assert (verdict.state, verdict.reason) == (state, reason)


def test_cloudflare_origin_error_says_so():
    assert "Cloudflare" in classify(Probe(status=522)).note


@pytest.mark.parametrize(
    "body",
    [
        REMOVAL_PAGE,
        "<p>This project has been removed following a DMCA request.</p>",
        "<h1>The site is no longer available</h1><p>We received a cease and desist letter.</p>",
    ],
)
def test_takedown_notice_detected(body):
    assert has_takedown_notice(body)


@pytest.mark.parametrize(
    "body",
    [
        GAME_PAGE,
        # Aviso legal de port que pede a cópia do jogador: cita direitos autorais, mas nada foi removido.
        "<p>To comply with copyright law, this website does not provide game data. Bring your own disc image.</p>",
        # Rodapé com canal de remoção não é aviso de remoção.
        "<canvas></canvas><footer>DMCA: if you want your content removed, write to us.</footer>",
        # A frase certa, mas em uma página longa (um fórum, uma notícia): não é a página do jogo fora do ar.
        "<p>This game was removed after a DMCA takedown.</p>" + "<p>texto de um fórum bem longo</p>" * 400,
        # Script com as palavras não conta: só o texto visível.
        "<canvas></canvas><script>var msg = 'This game was removed due to a DMCA takedown';</script>",
    ],
)
def test_takedown_notice_not_detected(body):
    assert not has_takedown_notice(body)


class Handler(BaseHTTPRequestHandler):
    flaky_calls = 0

    def log_message(self, *args):
        pass

    def _send(self, status, body="", headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        try:
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # o cliente desistiu de esperar: é o que o teste de tempo esgotado provoca

    def do_GET(self):
        path = self.path
        if path == "/ok":
            self._send(200, GAME_PAGE)
        elif path == "/desafio":
            self._send(403, CHALLENGE_PAGE, {"cf-mitigated": "challenge"})
        elif path == "/sumiu":
            self._send(404, "Not Found")
        elif path == "/erro":
            self._send(500, "Internal Server Error")
        elif path == "/aviso":
            self._send(200, REMOVAL_PAGE)
        elif path == "/redireciona":
            self._send(302, "", {"Location": "/ok"})
        elif path == "/lento":
            time.sleep(1.2)
            self._send(200, GAME_PAGE)
        elif path == "/instavel":
            type(self).flaky_calls += 1
            if type(self).flaky_calls == 1:
                self._send(500, "Internal Server Error")
            else:
                self._send(200, GAME_PAGE)
        elif path == "/grande":
            self._send(200, GAME_PAGE + "x" * (check_links.MAX_BYTES * 3))
        elif path == "/agente":
            self._send(200, self.headers.get("User-Agent", ""))
        else:
            self._send(404, "Not Found")


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def local_session() -> requests.Session:
    session = check_links.new_session()
    session.trust_env = False  # o servidor de teste é local: nada de proxy
    return session


FAST = {"pause": 0, "timeout": (2, 0.5)}


@pytest.mark.parametrize(
    "path, state, reason, status",
    [
        ("/ok", "online", "ok", 200),
        ("/redireciona", "online", "ok", 200),
        ("/grande", "online", "ok", 200),
        ("/desafio", "unverified", "bot_blocked", 403),
        ("/sumiu", "offline", "not_found", 404),
        ("/erro", "unstable", "server_error", 500),
        ("/aviso", "unstable", "takedown_notice", 200),
        ("/lento", "unstable", "timeout", None),
    ],
)
def test_check_url_against_local_server(server, path, state, reason, status):
    with local_session() as session:
        result, verdict = check_url(session, server + path, **FAST)
    assert (verdict.state, verdict.reason, result.status) == (state, reason, status)
    assert result.elapsed_ms is not None


def test_retry_recovers_from_a_passing_failure(server):
    Handler.flaky_calls = 0
    with local_session() as session:
        _, verdict = check_url(session, server + "/instavel", **FAST)
    assert verdict.state == "online"
    assert Handler.flaky_calls == 2


def test_blocked_site_is_not_hammered(server, monkeypatch):
    calls = []
    real_probe = check_links.probe
    monkeypatch.setattr(check_links, "probe", lambda *a, **k: calls.append(1) or real_probe(*a, **k))
    with local_session() as session:
        check_url(session, server + "/desafio", **FAST)
    assert len(calls) == 1


def test_robot_identifies_itself(server):
    with local_session() as session:
        result, _ = check_url(session, server + "/agente", **FAST)
    assert "LOKGAM" in result.body and "github.com" in result.body


def test_connection_refused_is_unstable():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    with local_session() as session:
        _, verdict = check_url(session, f"http://127.0.0.1:{closed_port}/", attempts=1, **FAST)
    assert (verdict.state, verdict.reason) == ("unstable", "connection_error")


def test_unknown_host_is_offline():
    with local_session() as session:
        _, verdict = check_url(session, "http://lokgam-nao-existe.invalid/", attempts=1, **FAST)
    assert (verdict.state, verdict.reason) == ("offline", "dns_error")


def test_run_writes_one_row_per_port_in_order(server):
    ports = [
        {"id": "a", "links": {"play": server + "/ok"}},
        {"id": "b", "links": {"play": server + "/sumiu"}},
        {"id": "c", "links": {"play": server + "/desafio"}},
    ]
    rows = run(ports, "2026-11-11T06:17:00Z", session_factory=local_session, **FAST)
    assert [row["port_id"] for row in rows] == ["a", "b", "c"]
    assert [row["state"] for row in rows] == ["online", "offline", "unverified"]
    assert {row["checked_at"] for row in rows} == {"2026-11-11T06:17:00Z"}
    assert all(row["method"] == "link_checker" and "response_ms" in row for row in rows)
    assert "note" not in rows[0] and rows[1]["note"]


def test_network_down_guard():
    down = [{"reason": "dns_error"}, {"reason": "timeout"}, {"reason": "connection_error"}]
    assert network_is_down(down)
    assert not network_is_down(down + [{"reason": "ok"}])
    assert not network_is_down(down[:1])


def test_summary_line_skips_empty_states():
    rows = [{"state": "online"}, {"state": "online"}, {"state": "unverified"}]
    assert summary_line(rows, "2026-11-11T06:17:00Z") == (
        "Conferência de links de 2026-11-11 06:17 UTC: 2 no ar, 1 não conferido"
    )


def test_append_rows_keeps_one_json_per_line(tmp_path):
    path = tmp_path / "checks.jsonl"
    path.write_text('{"port_id": "a"}', encoding="utf-8")  # arquivo sem quebra de linha no fim
    check_links.append_rows([{"port_id": "b"}, {"port_id": "c"}], path)
    assert path.read_text(encoding="utf-8").splitlines() == ['{"port_id": "a"}', '{"port_id": "b"}', '{"port_id": "c"}']

"""As páginas geradas: recebem os dados que esperam e não carregam endereço que não deveriam."""
import json
import re

import pytest

import build
import validate

DATA = re.compile(r'<script type="application/json" id="dados">(.*?)</script>', re.S)


@pytest.fixture(scope="module")
def pages():
    out = {}
    for name in ("index.html", "observatorio/index.html"):
        html = (validate.ROOT / "docs" / name).read_text(encoding="utf-8")
        out[name] = (html, json.loads(DATA.search(html).group(1).replace("<\\/", "</")))
    return out


def test_generated_pages_have_no_leftover_placeholder(pages):
    for html, _ in pages.values():
        assert "__DADOS__" not in html and "/*__BASE_CSS__*/" not in html and "/*__BASE_JS__*/" not in html


def test_storefront_receives_ports_events_and_catalogs(pages):
    _, data = pages["index.html"]
    assert {"repo", "last_check", "ports", "events", "catalogs"} <= set(data)
    ports, _, _ = validate.load_base()
    assert [p["id"] for p in data["ports"]] == [p["id"] for p in ports]


def test_observatory_receives_every_block_it_draws(pages):
    _, data = pages["observatorio/index.html"]
    assert {"totals", "availability", "events_by_month", "actors", "composition", "events", "catalogs", "base"} <= set(data)
    assert {"sources", "hosting"} <= set(data["catalogs"])
    assert {"ports", "games", "console_games", "fichas_linked", "top_games", "by_origin"} <= set(data["base"])


def test_every_id_the_observatory_script_asks_for_exists(pages):
    html, _ = pages["observatorio/index.html"]
    script = html[html.rindex("<script>"):]
    wanted = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", script))
    present = set(re.findall(r'\bid="([^"]+)"', html))
    assert wanted and wanted <= present, sorted(wanted - present)


def test_observatory_names_hosts_only_as_text(pages):
    html, data = pages["observatorio/index.html"]
    for row in data["catalogs"]["hosting"]["top"]:
        assert "/" not in row["host"] and f'href="https://{row["host"]}' not in html
    assert "://" not in json.dumps(data["base"]) and "://" not in json.dumps(data["catalogs"])


def test_build_is_deterministic(pages):
    ports, events, checks = validate.load_base()
    again = build.embed(build.observatory_payload(ports, events, checks))
    assert again == DATA.search(pages["observatorio/index.html"][0]).group(1)

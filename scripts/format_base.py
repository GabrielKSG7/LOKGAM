#!/usr/bin/env python3
"""Reescreve data/ports.json no formato canônico, para o diff de cada ficha ficar pequeno.

Recuo de dois espaços; listas de texto e a capa (label) ficam em uma linha só.

    python3 scripts/format_base.py          regrava o arquivo
    python3 scripts/format_base.py --check  só avisa se estiver fora do formato
"""
from __future__ import annotations

import json
import re
import sys

from validate import ROOT

PORTS = ROOT / "data" / "ports.json"
_STRING = r'"(?:[^"\\]|\\.)*"'
_STRING_LIST = re.compile(r"\[\s*%s(?:,\s*%s)*\s*\]" % (_STRING, _STRING))
_LABEL = re.compile(r'"label": \{([^{}]*)\}')
_PAIR = re.compile(r"(%s): (%s)" % (_STRING, _STRING))


def format_ports(ports: list[dict]) -> str:
    text = json.dumps(ports, ensure_ascii=False, indent=2)
    text = _STRING_LIST.sub(lambda m: "[" + ", ".join(re.findall(_STRING, m.group(0))) + "]", text)
    text = _LABEL.sub(
        lambda m: '"label": { ' + ", ".join(f"{key}: {value}" for key, value in _PAIR.findall(m.group(1))) + " }",
        text,
    )
    return text + "\n"


def main(argv: list[str]) -> int:
    current = PORTS.read_text(encoding="utf-8")
    wanted = format_ports(json.loads(current))
    if "--check" in argv:
        if current != wanted:
            print("data/ports.json está fora do formato. Rode: python3 scripts/format_base.py")
            return 1
        return 0
    PORTS.write_text(wanted, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

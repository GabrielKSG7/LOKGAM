#!/usr/bin/env python3
"""Camada ouro: roda os modelos dbt sobre a bronze e exporta as tabelas finais.

O dbt (com DuckDB) lê os arquivos de data/bronze, refaz a história de cada versão listada,
roda os testes de dados e materializa as tabelas gold_*. Este script exporta essas tabelas
para data/gold/<tabela>.json, que o site lê. O banco DuckDB é descartável e fica fora do Git.

Uso: python3 scripts/gold.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from validate import ROOT

PROJECT = ROOT / "dbt"
GOLD = ROOT / "data" / "gold"
TABLES = ("gold_findings", "gold_daily_status", "gold_collective_outages", "gold_outages", "gold_catalog_daily")


def run_dbt(data_dir: Path | str = "data", database: Path | None = None, target: Path | None = None) -> None:
    """dbt build: modelos e testes. Para no primeiro erro.

    Roda em outro processo, para o banco ficar livre para a leitura logo depois.
    """
    database = Path(database or PROJECT / "target" / "lokgam.duckdb")
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()  # cada execução recomeça do zero, a partir dos arquivos
    env = {**os.environ, "LOKGAM_DUCKDB": str(database), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    dbt = shutil.which("dbt", path=f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}")
    if dbt is None:
        raise SystemExit("dbt não encontrado. Instale as dependências: pip install -r requirements.txt")
    args = [dbt, "build", "--project-dir", str(PROJECT), "--profiles-dir", str(PROJECT),
            "--vars", json.dumps({"data_dir": str(data_dir)}), "--quiet", "--fail-fast"]
    if target:
        args += ["--target-path", str(target), "--log-path", str(Path(target) / "logs")]
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("dbt build falhou:\n" + (result.stdout + result.stderr)[-4000:])


def _plain(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def read_tables(database: Path | None = None) -> dict[str, list[dict]]:
    import duckdb

    database = Path(database or PROJECT / "target" / "lokgam.duckdb")
    with duckdb.connect(str(database), read_only=True) as con:
        out = {}
        for table in TABLES:
            cursor = con.execute(f"select * from {table} order by all")
            names = [column[0] for column in cursor.description]
            out[table] = [{name: _plain(value) for name, value in zip(names, row)} for row in cursor.fetchall()]
    return out


def render(rows: list[dict]) -> str:
    """Uma linha por registro, para o diff de cada dia ficar legível."""
    if not rows:
        return "[]\n"
    return "[\n" + ",\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n]\n"


def main() -> int:
    run_dbt()
    GOLD.mkdir(parents=True, exist_ok=True)
    for table, rows in read_tables().items():
        (GOLD / f"{table.removeprefix('gold_')}.json").write_text(render(rows), encoding="utf-8")
        print(f"data/gold/{table.removeprefix('gold_')}.json: {len(rows)} linhas")
    return 0


if __name__ == "__main__":
    sys.exit(main())

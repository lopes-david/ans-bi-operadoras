"""CLI local: `uv run ans-bi --help`.

Útil para desenvolver e para o backfill histórico: a máquina local processa de graça e
grava direto no S3 (upload para a AWS não é cobrado).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .config import load_settings
from .sources import SOURCES, Task


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _run_one(task_dict: dict) -> dict:
    from .pipeline import run_task
    from .storage import Lake

    settings = load_settings()
    return run_task(settings, Lake(settings), Task.from_dict(task_dict))


def main(argv: list[str] | None = None) -> None:
    _load_dotenv()
    parser = argparse.ArgumentParser(prog="ans-bi", description="Pipeline de dados abertos da ANS")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sources", help="lista as fontes disponíveis")

    for name in ("plan", "run"):
        p = sub.add_parser(name, help=("mostra" if name == "plan" else "executa") + " o que mudou na ANS")
        p.add_argument("-s", "--source", action="append", choices=list(SOURCES), help="repetível; padrão: todas")
        p.add_argument("--backfill", action="store_true", help="considera todo o histórico, não só os últimos meses")
        p.add_argument("--limit", type=int, help="processa no máximo N arquivos")
        if name == "run":
            p.add_argument("-j", "--jobs", type=int, default=2, help="arquivos em paralelo (padrão 2)")
            p.add_argument("--no-gold", action="store_true", help="não reconstrói a gold ao final")

    g = sub.add_parser("gold", help="reconstrói a camada gold e o manifest do site")
    g.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from . import gold, pipeline
    from .storage import Lake

    settings = load_settings()
    lake = Lake(settings)
    logging.info("lake: %s", settings.lake_uri)

    if args.cmd == "sources":
        for s in SOURCES.values():
            print(f"{s.name:18} {s.description}")
        return

    if args.cmd == "gold":
        print(json.dumps(gold.build(settings, lake, force=args.force), indent=1, default=str))
        return

    tasks = pipeline.plan(settings, lake, args.source or list(SOURCES), backfill=args.backfill)
    if args.limit:
        tasks = tasks[: args.limit]

    if args.cmd == "plan":
        for t in tasks:
            print(f"{t.source:16} {t.key:20} {t.url}")
        print(f"{len(tasks)} arquivo(s) a processar")
        return

    errors = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(_run_one, t.to_dict()): t for t in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            t = futures[fut]
            try:
                r = fut.result()
                print(f"[{i}/{len(tasks)}] ok   {t.source}/{t.key} ({r['seconds']}s)")
            except Exception as exc:
                errors += 1
                print(f"[{i}/{len(tasks)}] ERRO {t.source}/{t.key}: {exc}")
    if not args.no_gold and tasks and not errors:
        print(json.dumps(gold.build(settings, lake), indent=1, default=str))
    if errors:
        raise SystemExit(f"{errors} arquivo(s) falharam; rode novamente para reprocessar só eles")

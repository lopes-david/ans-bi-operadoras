"""Planner (o que mudou na ANS) e worker (baixa, transforma e grava na camada silver)."""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
import zipfile
from pathlib import Path

import duckdb

from .config import Settings
from .http import download
from .sources import SOURCES, Task, sql_text
from .storage import Lake

log = logging.getLogger(__name__)

DONE_PREFIX = "state/done"


def sql_literal(value: str | Path) -> str:
    """Literal SQL escapado, para onde o DuckDB não aceita parâmetros (COPY TO, SET, read_csv)."""
    return "'" + str(value).replace("'", "''") + "'"


def render_sql(name: str, **values: str) -> str:
    """Substitui {placeholders} sem str.format (os SQLs têm regex com chaves, ex.: \\d{4})."""
    text = sql_text(name)
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def connect(settings: Settings, s3: bool = False) -> duckdb.DuckDBPyConnection:
    tmp = settings.work_dir / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(config={
        "memory_limit": settings.duckdb_memory_limit,
        "threads": settings.duckdb_threads,
        "temp_directory": str(tmp),
        "preserve_insertion_order": False,  # permite streaming com menos memória
    })  # fmt: skip
    if s3:
        _enable_s3(con)
    return con


def _enable_s3(con: duckdb.DuckDBPyConnection) -> None:
    ext_dir = Path(__file__).parent / "duckdb_extensions"
    if ext_dir.exists():  # na Lambda a extensão vai empacotada (sem download em runtime)
        con.execute(f"SET extension_directory = {sql_literal(ext_dir)}")
    else:
        con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")

    import boto3  # credenciais do boto3 evitam empacotar a extensão "aws" do DuckDB

    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()
    parts = [
        "TYPE s3",
        f"KEY_ID {sql_literal(creds.access_key)}",
        f"SECRET {sql_literal(creds.secret_key)}",
        f"REGION {sql_literal(session.region_name or 'sa-east-1')}",
    ]
    if creds.token:
        parts.append(f"SESSION_TOKEN {sql_literal(creds.token)}")
    con.execute(f"CREATE SECRET lake ({', '.join(parts)})")


# --- controle de versões ------------------------------------------------------------------


def _marker(task: Task) -> str:
    digest = hashlib.sha1(task.version.encode()).hexdigest()[:12]
    return f"{DONE_PREFIX}/{task.source}/{task.key}@{digest}"


def done_markers(lake: Lake, source: str) -> set[str]:
    return set(lake.list_keys(f"{DONE_PREFIX}/{source}/"))


def plan(settings: Settings, lake: Lake, sources: list[str], backfill: bool = False) -> list[Task]:
    pending: list[Task] = []
    for name in sources:
        done = done_markers(lake, name)
        found = list(SOURCES[name].discover(settings, backfill))
        new = [t for t in found if _marker(t) not in done]
        log.info("%s: %d arquivos na ANS, %d novos/alterados", name, len(found), len(new))
        pending += new
    return pending


def _mark_done(lake: Lake, task: Task) -> None:
    marker = _marker(task)
    stale = [k for k in lake.list_keys(f"{DONE_PREFIX}/{task.source}/{task.key}@") if k != marker]
    lake.write_json(marker, {**task.to_dict(), "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    lake.delete_keys(stale)


# --- worker ---------------------------------------------------------------------------------


def _detect_encoding(path: Path) -> str:
    with open(path, "rb") as fh:
        sample = fh.read(4 * 1024 * 1024)
    # corta no último \n para não quebrar um caractere multibyte no meio
    sample = sample[: sample.rfind(b"\n") + 1] or sample
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def _extract_csv(archive: Path, dest_dir: Path) -> Path:
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if m.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"{archive.name}: esperado 1 CSV, encontrado {len(members)}")
        target = dest_dir / Path(members[0].filename).name
        with zf.open(members[0]) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
    archive.unlink()  # libera espaço em disco antes da transformação
    return target


def _csv_relation(path: Path) -> str:
    enc = _detect_encoding(path)
    return (
        f"read_csv({sql_literal(path)}, delim=';', quote='\"', header=true, all_varchar=true, "
        f"encoding={sql_literal(enc)}, null_padding=true, max_line_size=10000000)"
    )


def run_task(settings: Settings, lake: Lake, task: Task) -> dict:
    started = time.monotonic()
    src = SOURCES[task.source]
    job_dir = settings.work_dir / "jobs" / hashlib.sha1(f"{task.source}/{task.key}".encode()).hexdigest()[:10]
    shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True)
    try:
        filename = task.url.rsplit("/", 1)[-1]
        local = job_dir / filename
        size = download(task.url, local)
        if local.suffix.lower() == ".zip":
            local = _extract_csv(local, job_dir)
        relation = _csv_relation(local)

        con = connect(settings)
        rows = {}
        for out in src.outputs(task):
            query = render_sql(out.sql, src=relation, **out.fmt)
            if out.drop:
                query = f"SELECT * EXCLUDE ({', '.join(out.drop)}) FROM ({query})"
            parquet = job_dir / f"{Path(out.sql).stem}.parquet"
            con.execute(
                f"COPY ({query}) TO {sql_literal(parquet)} (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 250000)"
            )
            rows[out.lake_key] = con.execute("SELECT count(*) FROM read_parquet(?)", [str(parquet)]).fetchone()[0]
            lake.upload_file(parquet, out.lake_key)
        con.close()
        _mark_done(lake, task)
        result = {
            "source": task.source,
            "key": task.key,
            "download_bytes": size,
            "rows": rows,
            "seconds": round(time.monotonic() - started, 1),
        }
        log.info("ok %s", result)
        return result
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

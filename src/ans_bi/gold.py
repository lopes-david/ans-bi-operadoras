"""Camada gold: marts pequenos e prontos para o dashboard e o Athena.

Lê a silver direto do lake (httpfs no S3), grava cada mart em dois lugares:
  gold/<mart>/data.parquet            -> nome estável, usado pelas tabelas do Athena
  site/data/<mart>.<hash>.parquet     -> nome imutável, servido pelo CloudFront com cache longo
e publica site/data/manifest.json (cache curto) apontando para os arquivos atuais.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from importlib import resources

from .config import Settings
from .pipeline import DONE_PREFIX, connect, sql_literal
from .sources import SOURCES
from .storage import Lake

log = logging.getLogger(__name__)

# views da silver -> padrão de arquivos (partições Hive)
SILVER_VIEWS = {
    "operadoras": "silver/operadoras/*/*/data.parquet",
    "beneficiarios_municipio": "silver/beneficiarios_municipio/*/*/data.parquet",
    "beneficiarios_perfil": "silver/beneficiarios_perfil/*/*/data.parquet",
    "nip": "silver/nip/*/data.parquet",
    "igr": "silver/igr/data.parquet",
    "idss": "silver/idss/*.parquet",
    "tiss_hospitalar": "silver/tiss_hospitalar/*/*/data.parquet",
}
OPTIONAL_VIEWS = {"tiss_hospitalar"}
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"


def _gold_sqls() -> list[tuple[str, str]]:
    folder = resources.files("ans_bi").joinpath("sql", "gold")
    files = sorted(f.name for f in folder.iterdir() if f.name.endswith(".sql"))
    # "07_igr_mensal.sql" -> ("igr_mensal", sql)
    return [(n.removesuffix(".sql").split("_", 1)[1], folder.joinpath(n).read_text("utf-8")) for n in files]


def fingerprint(lake: Lake) -> str:
    """Muda sempre que algum arquivo da silver é reprocessado."""
    keys = sorted(k for name in SOURCES for k in lake.list_keys(f"{DONE_PREFIX}/{name}/"))
    return hashlib.sha1("\n".join(keys).encode()).hexdigest()


def build(settings: Settings, lake: Lake, force: bool = False) -> dict:
    started = time.monotonic()
    fp = fingerprint(lake)
    state = lake.read_json("state/gold.json") or {}
    if not force and state.get("fingerprint") == fp:
        log.info("gold: silver sem mudanças desde %s", state.get("built_at"))
        return {"status": "skipped", "built_at": state.get("built_at")}

    out_dir = settings.work_dir / "gold"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    con = connect(settings, s3=settings.is_s3)

    missing = []
    for view, pattern in SILVER_VIEWS.items():
        if not lake.exists(pattern.split("*")[0].rstrip("/")):
            missing.append(view)
            continue
        con.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_parquet({sql_literal(lake.uri(pattern))}, "
            "hive_partitioning = true, union_by_name = true)"
        )
    required_missing = [v for v in missing if v not in OPTIONAL_VIEWS]
    if required_missing:
        raise RuntimeError(f"silver incompleta, faltam: {required_missing} (rode o pipeline antes)")

    manifest_tables = {}
    for mart, sql in _gold_sqls():
        if any(v in missing and v in sql for v in OPTIONAL_VIEWS):
            log.info("gold: pulando %s (fonte opcional ausente)", mart)
            continue
        local = out_dir / f"{mart}.parquet"
        con.execute(f"COPY ({sql}) TO {sql_literal(local)} (FORMAT parquet, COMPRESSION zstd)")
        # os próximos marts consultam este pelo nome
        con.execute(f"CREATE VIEW {mart} AS SELECT * FROM read_parquet({sql_literal(local)})")
        rows = con.execute(f"SELECT count(*) FROM {mart}").fetchone()[0]
        digest = hashlib.sha1(local.read_bytes()).hexdigest()[:12]
        site_file = f"{mart}.{digest}.parquet"
        lake.upload_file(local, f"gold/{mart}/data.parquet")
        lake.upload_file(local, f"site/data/{site_file}", cache_control=IMMUTABLE)
        manifest_tables[mart] = {"file": site_file, "rows": rows, "bytes": local.stat().st_size}
        log.info("gold: %s -> %d linhas, %.1f KB", mart, rows, local.stat().st_size / 1024)

    ref = con.execute("SELECT max(competencia) FROM beneficiarios_mensal").fetchone()[0]
    glue_db = os.environ.get("ANS_GLUE_DATABASE")
    if settings.is_s3 and glue_db:
        from . import catalog

        present = [v for v in SILVER_VIEWS if v not in missing]
        catalog.register(con, glue_db, lake.uri("").rstrip("/"), present, list(manifest_tables), settings.start_year)
    con.close()
    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest = {"generated_at": built_at, "competencia_ref": str(ref), "tables": manifest_tables}

    # mantém a geração anterior (clientes com manifest antigo em cache ainda a encontram)
    previous = lake.read_json("site/data/manifest.json") or {}
    keep = {"manifest.json"}
    keep |= {t["file"] for t in manifest_tables.values()}
    keep |= {t["file"] for t in previous.get("tables", {}).values()}
    lake.write_json("site/data/manifest.json", manifest, cache_control=SHORT)
    stale = [k for k in lake.list_keys("site/data/") if k.removeprefix("site/data/") not in keep]
    lake.delete_keys(stale)

    lake.write_json("state/gold.json", {"fingerprint": fp, "built_at": built_at, "competencia_ref": str(ref)})
    shutil.rmtree(out_dir, ignore_errors=True)
    return {
        "status": "built",
        "competencia_ref": str(ref),
        "tables": {k: v["rows"] for k, v in manifest_tables.items()},
        "seconds": round(time.monotonic() - started, 1),
    }

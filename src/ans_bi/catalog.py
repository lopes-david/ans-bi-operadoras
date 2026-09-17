"""Registra silver e gold no Glue Data Catalog (para o Athena) sem crawler.

O esquema vem do próprio DuckDB, então as tabelas acompanham qualquer mudança nos SQLs.
Partições da silver usam *partition projection*: nada de MSCK REPAIR nem crawler pago.
"""

from __future__ import annotations

import logging
import re

import duckdb

from .config import UFS

log = logging.getLogger(__name__)

_UF_ENUM = ",".join((*UFS, "XX"))


def _projection(start_year: int) -> dict[str, dict]:
    month = {
        "type": "date",
        "format": "yyyy-MM",
        "range": f"{start_year}-01,NOW",
        "interval": "1",
        "interval.unit": "MONTHS",
    }
    uf = {"type": "enum", "values": _UF_ENUM}
    return {
        "operadoras": {
            "situacao": {"type": "enum", "values": "ativa,cancelada"},
            "snapshot": {
                "type": "date",
                "format": "yyyy-MM-dd",
                "range": "2026-01-01,NOW",
                "interval": "1",
                "interval.unit": "DAYS",
            },
        },
        "beneficiarios_municipio": {"competencia": month, "uf": uf},
        "beneficiarios_perfil": {"competencia": month, "uf": uf},
        "nip": {"ano": {"type": "integer", "range": f"{start_year},2100"}},
        "tiss_hospitalar": {"competencia": month, "uf": uf},
    }


def _hive_type(duck_type: str) -> str:
    t = duck_type.upper()
    if m := re.fullmatch(r"DECIMAL\((\d+),\s*(\d+)\)", t):
        return f"decimal({m[1]},{m[2]})"
    return {
        "VARCHAR": "string",
        "BOOLEAN": "boolean",
        "TINYINT": "tinyint",
        "SMALLINT": "smallint",
        "INTEGER": "int",
        "BIGINT": "bigint",
        "HUGEINT": "decimal(38,0)",
        "FLOAT": "float",
        "DOUBLE": "double",
        "DATE": "date",
        "TIMESTAMP": "timestamp",
    }.get(t, "string")


def _columns(con: duckdb.DuckDBPyConnection, relation: str, skip: set[str]) -> list[dict]:
    rows = con.execute(f"DESCRIBE {relation}").fetchall()
    return [{"Name": r[0], "Type": _hive_type(r[1])} for r in rows if r[0] not in skip]


def _upsert(glue, database: str, table: dict) -> None:
    try:
        glue.update_table(DatabaseName=database, TableInput=table)
    except glue.exceptions.EntityNotFoundException:
        glue.create_table(DatabaseName=database, TableInput=table)


def register(
    con: duckdb.DuckDBPyConnection,
    database: str,
    bucket_uri: str,
    silver_views: list[str],
    gold_marts: list[str],
    start_year: int,
) -> None:
    import boto3

    glue = boto3.client("glue")
    projections = _projection(start_year)
    serde = {
        "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
        "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
        "SerdeInfo": {"SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"},
    }

    for view in silver_views:
        proj = projections.get(view, {})
        params = {"classification": "parquet", "EXTERNAL": "TRUE"}
        if proj:
            params["projection.enabled"] = "true"
            for col, spec in proj.items():
                for k, v in spec.items():
                    params[f"projection.{col}.{k}"] = v
        partition_keys = [{"Name": c, "Type": "int" if s["type"] == "integer" else "string"} for c, s in proj.items()]
        _upsert(glue, database, {
            "Name": f"silver_{view}",
            "TableType": "EXTERNAL_TABLE",
            "Parameters": params,
            "PartitionKeys": partition_keys,
            "StorageDescriptor": {
                **serde,
                "Columns": _columns(con, view, skip=set(proj)),
                "Location": f"{bucket_uri}/silver/{view}/",
            },
        })  # fmt: skip

    for mart in gold_marts:
        _upsert(glue, database, {
            "Name": mart,
            "TableType": "EXTERNAL_TABLE",
            "Parameters": {"classification": "parquet", "EXTERNAL": "TRUE"},
            "StorageDescriptor": {
                **serde,
                "Columns": _columns(con, mart, skip=set()),
                "Location": f"{bucket_uri}/gold/{mart}/",
            },
        })  # fmt: skip
    log.info("glue: %d tabelas silver e %d gold registradas em %s", len(silver_views), len(gold_marts), database)

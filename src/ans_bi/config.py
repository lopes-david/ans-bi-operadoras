"""Configuração via variáveis de ambiente (mesmo código roda local e na Lambda)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ANS_BASE_URL = "https://dadosabertos.ans.gov.br/FTP/PDA"
USER_AGENT = "ans-bi-operadoras/0.1 (+https://github.com/lopes-david/ans-bi-operadoras)"


@dataclass(frozen=True)
class Settings:
    # "s3://bucket" na AWS ou um diretório local (ex.: "data/lake")
    lake_uri: str
    # diretório de trabalho temporário (na Lambda, só /tmp é gravável)
    work_dir: Path
    # quantos meses para trás o planner olha nas bases mensais (backfill ignora)
    lookback_months: int
    # limites do DuckDB: a Lambda tem 2 vCPUs a partir de ~1,8 GB de memória
    duckdb_memory_limit: str
    duckdb_threads: int
    # fila SQS de tarefas (vazio = executa tudo em linha, modo local)
    queue_url: str
    # UFs das bases por estado (ICB e TISS)
    ufs: tuple[str, ...]
    # ano inicial do histórico nas bases mensais/anuais
    start_year: int

    @property
    def is_s3(self) -> bool:
        return self.lake_uri.startswith("s3://")


UFS = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)  # fmt: skip


def load_settings() -> Settings:
    in_lambda = "AWS_LAMBDA_FUNCTION_NAME" in os.environ
    default_work = "/tmp/ans-bi" if in_lambda else "data/work"
    ufs = os.environ.get("ANS_UFS", "")
    return Settings(
        lake_uri=os.environ.get("ANS_LAKE_URI", "data/lake").rstrip("/"),
        work_dir=Path(os.environ.get("ANS_WORK_DIR", default_work)),
        lookback_months=int(os.environ.get("ANS_LOOKBACK_MONTHS", "3")),
        duckdb_memory_limit=os.environ.get("ANS_DUCKDB_MEMORY", "2GB"),
        duckdb_threads=int(os.environ.get("ANS_DUCKDB_THREADS", "2")),
        queue_url=os.environ.get("ANS_QUEUE_URL", ""),
        ufs=tuple(u.strip().upper() for u in ufs.split(",") if u.strip()) or UFS,
        start_year=int(os.environ.get("ANS_START_YEAR", "2021")),
    )

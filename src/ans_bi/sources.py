"""Catálogo das fontes da ANS: como descobrir arquivos novos e como transformá-los (camada silver).

Cada arquivo publicado pela ANS vira uma `Task` independente. A `version` vem do índice do
servidor (data de modificação + tamanho), então o planner sabe o que mudou sem baixar nada.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from importlib import resources

from .config import ANS_BASE_URL, Settings
from .http import Entry, list_dir


@dataclass(frozen=True)
class Task:
    source: str
    key: str  # identificador estável do arquivo dentro da fonte
    url: str
    version: str
    params: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(**d)


@dataclass(frozen=True)
class Output:
    """Uma consulta SQL da camada silver e a partição (chave no lake) que ela grava."""

    sql: str
    lake_key: str
    fmt: dict[str, str] = field(default_factory=dict)
    # colunas que já estão no caminho (Hive) e não podem se repetir no arquivo (regra do Athena)
    drop: tuple[str, ...] = ()


@dataclass(frozen=True)
class Source:
    name: str
    description: str
    discover: Callable[[Settings, bool], Iterator[Task]]
    outputs: Callable[[Task], list[Output]]


def sql_text(name: str) -> str:
    return resources.files("ans_bi").joinpath("sql", name).read_text(encoding="utf-8")


def _entries(path: str) -> list[Entry]:
    return list_dir(f"{ANS_BASE_URL}/{path}")


def _recent(items: list[str], n: int, backfill: bool) -> list[str]:
    return items if backfill else items[-n:]


# --- operadoras (cadastro) -----------------------------------------------------------------

_CADOP = {
    "ativa": ("operadoras_de_plano_de_saude_ativas", "Relatorio_cadop.csv"),
    "cancelada": ("operadoras_de_plano_de_saude_canceladas", "Relatorio_cadop_canceladas.csv"),
}


def _discover_operadoras(settings: Settings, backfill: bool) -> Iterator[Task]:
    for situacao, (folder, filename) in _CADOP.items():
        for e in _entries(folder):
            if e.name == filename:
                snapshot = e.modified[:10]
                yield Task(
                    source="operadoras",
                    key=f"{situacao}/{snapshot}",
                    url=f"{ANS_BASE_URL}/{folder}/{filename}",
                    version=e.version,
                    params={"situacao": situacao, "snapshot": snapshot},
                )


def _outputs_operadoras(t: Task) -> list[Output]:
    if t.params["situacao"] == "cancelada":
        cancel_cols = (
            "TRY_CAST(DATA_DESCREDENCIAMENTO AS DATE) AS data_descredenciamento,\n"
            "    nullif(trim(MOTIVO_DO_DESCREDENCIAMENTO), '') AS motivo_descredenciamento"
        )
    else:
        cancel_cols = "NULL::DATE AS data_descredenciamento,\n    NULL::VARCHAR AS motivo_descredenciamento"
    key = f"silver/operadoras/situacao={t.params['situacao']}/snapshot={t.params['snapshot']}/data.parquet"
    return [Output("silver/operadoras.sql", key, {"cancel_cols": cancel_cols})]


# --- beneficiários consolidados (ICB), mensal por UF --------------------------------------

_ICB = "informacoes_consolidadas_de_beneficiarios-024"
_ICB_FILE = re.compile(r"pda-024-icb-(?P<uf>[A-Z]{2})-(?P<ano>\d{4})_(?P<mes>\d{2})\.zip$")


def _discover_icb(settings: Settings, backfill: bool) -> Iterator[Task]:
    months = sorted(
        e.name.rstrip("/")
        for e in _entries(_ICB)
        if e.is_dir and re.fullmatch(r"\d{6}/", e.name) and int(e.name[:4]) >= settings.start_year
    )
    wanted_ufs = set(settings.ufs) | {"XX"}  # XX = UF não informada
    for month in _recent(months, settings.lookback_months, backfill):
        for e in _entries(f"{_ICB}/{month}"):
            m = _ICB_FILE.match(e.name)
            if not m or m["uf"] not in wanted_ufs:
                continue
            comp = f"{m['ano']}-{m['mes']}"
            yield Task(
                source="beneficiarios",
                key=f"{comp}/{m['uf']}",
                url=f"{ANS_BASE_URL}/{_ICB}/{month}/{e.name}",
                version=e.version,
                params={"competencia": comp, "uf": m["uf"]},
            )


def _outputs_icb(t: Task) -> list[Output]:
    part = f"competencia={t.params['competencia']}/uf={t.params['uf']}/data.parquet"
    return [
        Output("silver/icb_municipio.sql", f"silver/beneficiarios_municipio/{part}", drop=("competencia", "uf")),
        Output("silver/icb_perfil.sql", f"silver/beneficiarios_perfil/{part}", drop=("competencia", "uf")),
    ]


# --- NIP (reclamações), um CSV por ano -----------------------------------------------------

_NIP = "demandas_dos_consumidores_nip"
_NIP_FILE = re.compile(r"pda-013-demandas_dos_consumidores_nip-(?P<ano>\d{4})\.csv$")


def _discover_nip(settings: Settings, backfill: bool) -> Iterator[Task]:
    for e in _entries(_NIP):
        m = _NIP_FILE.match(e.name)
        if m and int(m["ano"]) >= settings.start_year:
            yield Task("nip", m["ano"], f"{ANS_BASE_URL}/{_NIP}/{e.name}", e.version, {"ano": m["ano"]})


def _outputs_nip(t: Task) -> list[Output]:
    return [Output("silver/nip.sql", f"silver/nip/ano={t.params['ano']}/data.parquet")]


# --- IGR e IDSS (arquivos únicos) ---------------------------------------------------------


def _discover_single(source: str, folder: str, pattern: str) -> Callable[[Settings, bool], Iterator[Task]]:
    rx = re.compile(pattern)

    def discover(settings: Settings, backfill: bool) -> Iterator[Task]:
        for e in _entries(folder):
            m = rx.match(e.name)
            if m:
                part = m.groupdict().get("part") or "all"
                yield Task(source, part, f"{ANS_BASE_URL}/{folder}/{e.name}", e.version, {"part": part})

    return discover


def _outputs_igr(t: Task) -> list[Output]:
    return [Output("silver/igr.sql", "silver/igr/data.parquet")]


def _outputs_idss(t: Task) -> list[Output]:
    return [Output("silver/idss.sql", f"silver/idss/{t.params['part']}.parquet")]


# --- TISS hospitalar (consolidado), mensal por UF -----------------------------------------

_TISS = "TISS/HOSPITALAR"
_TISS_FILE = re.compile(r"(?P<uf>[A-Z]{2})_(?P<ano>\d{4})(?P<mes>\d{2})_HOSP_CONS\.zip$")


def _discover_tiss(settings: Settings, backfill: bool) -> Iterator[Task]:
    years = sorted(
        e.name.rstrip("/")
        for e in _entries(_TISS)
        if e.is_dir and re.fullmatch(r"\d{4}/", e.name) and int(e.name[:4]) >= settings.start_year
    )
    # a ANS republica o ano corrente e o anterior; no dia a dia basta olhar os 2 últimos
    for year in _recent(years, 2, backfill):
        for uf in settings.ufs:
            for e in _entries(f"{_TISS}/{year}/{uf}"):
                m = _TISS_FILE.match(e.name)
                if m:
                    comp = f"{m['ano']}-{m['mes']}"
                    yield Task(
                        source="tiss_hospitalar",
                        key=f"{comp}/{uf}",
                        url=f"{ANS_BASE_URL}/{_TISS}/{year}/{uf}/{e.name}",
                        version=e.version,
                        params={"competencia": comp, "uf": uf},
                    )


def _outputs_tiss(t: Task) -> list[Output]:
    part = f"competencia={t.params['competencia']}/uf={t.params['uf']}/data.parquet"
    return [Output("silver/tiss_hosp.sql", f"silver/tiss_hospitalar/{part}")]


SOURCES: dict[str, Source] = {
    s.name: s
    for s in [
        Source("operadoras", "Cadastro de operadoras ativas e canceladas", _discover_operadoras, _outputs_operadoras),
        Source("beneficiarios", "Beneficiários consolidados (ICB), mensal por UF", _discover_icb, _outputs_icb),
        Source("nip", "Demandas de consumidores (NIP), anual", _discover_nip, _outputs_nip),
        Source(
            "igr",
            "Índice Geral de Reclamações",
            _discover_single("igr", "IGR/IGR_versao_2023", r"pda-023-igr\.csv$"),
            _outputs_igr,
        ),
        Source(
            "idss",
            "Histórico do IDSS",
            _discover_single("idss", "historico_idss-020", r"pda-020-historico-idss-(?P<part>\d{4}_\d{4})\.csv$"),
            _outputs_idss,
        ),
        Source("tiss_hospitalar", "TISS hospitalar consolidado", _discover_tiss, _outputs_tiss),
    ]
}

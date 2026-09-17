"""Testes sem rede: o download é substituído por cópia das fixtures."""

import shutil
from pathlib import Path

import duckdb
import pytest

from ans_bi import gold, pipeline
from ans_bi.config import load_settings
from ans_bi.http import parse_listing
from ans_bi.sources import Task
from ans_bi.storage import Lake

FIXTURES = Path(__file__).parent / "fixtures"

LISTING = """
<tr><td valign="top"><img src="/icons/back.gif" alt="[PARENTDIR]"></td><td><a href="/FTP/PDA/IGR/">Parent Directory</a></td><td>&nbsp;</td><td align="right">  - </td><td>&nbsp;</td></tr>
<tr><td valign="top"><img src="/icons/folder.gif" alt="[DIR]"></td><td><a href="202607/">202607/</a></td><td align="right">2026-09-04 12:02  </td><td align="right">  - </td><td>&nbsp;</td></tr>
<tr><td valign="top"><img src="/icons/text.gif" alt="[TXT]"></td><td><a href="pda-023-igr.csv">pda-023-igr.csv</a>        </td><td align="right">2026-09-10 08:00  </td><td align="right"> 16M</td><td>&nbsp;</td></tr>
<tr><td valign="top"><img src="/icons/text.gif" alt="[TXT]"></td><td><a href="Ficha%20T%C3%A9cnica.pdf">Ficha T&eacute;..&gt;</a></td><td align="right">2024-04-16 15:26  </td><td align="right">143K</td><td>&nbsp;</td></tr>
"""  # noqa: E501


def test_parse_listing():
    entries = parse_listing(LISTING)
    assert [e.name for e in entries] == ["202607/", "pda-023-igr.csv", "Ficha Técnica.pdf"]
    assert entries[0].is_dir and not entries[1].is_dir
    assert entries[1].version == "2026-09-10 08:00|16M"


TASKS = [
    Task(
        "operadoras", "ativa/2026-09-16", "x/Relatorio_cadop.csv", "v1", {"situacao": "ativa", "snapshot": "2026-09-16"}
    ),  # noqa: E501
    Task(
        "operadoras",
        "cancelada/2026-09-16",
        "x/Relatorio_cadop_canceladas.csv",
        "v1",
        {"situacao": "cancelada", "snapshot": "2026-09-16"},
    ),
    Task("beneficiarios", "2025-07/SP", "x/pda-024-icb-SP-2025_07.zip", "v1", {"competencia": "2025-07", "uf": "SP"}),
    Task("beneficiarios", "2026-07/SP", "x/pda-024-icb-SP-2026_07.zip", "v1", {"competencia": "2026-07", "uf": "SP"}),
    Task("nip", "2026", "x/pda-013-demandas_dos_consumidores_nip-2026.csv", "v1", {"ano": "2026"}),
    Task("igr", "all", "x/pda-023-igr.csv", "v1", {"part": "all"}),
    Task("idss", "2016_2025", "x/pda-020-historico-idss-2016_2025.csv", "v1", {"part": "2016_2025"}),
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANS_LAKE_URI", str(tmp_path / "lake"))
    monkeypatch.setenv("ANS_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.delenv("ANS_GLUE_DATABASE", raising=False)

    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / url.rsplit("/", 1)[-1], dest)
        return dest.stat().st_size

    monkeypatch.setattr(pipeline, "download", fake_download)
    settings = load_settings()
    return settings, Lake(settings)


def test_run_task_writes_partitions_and_marker(env):
    settings, lake = env
    result = pipeline.run_task(settings, lake, TASKS[2])
    key = "silver/beneficiarios_municipio/competencia=2025-07/uf=SP/data.parquet"
    assert result["rows"][key] == 3
    cols = duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{lake.uri(key)}', hive_partitioning = false)").fetchall()
    names = {c[0] for c in cols}
    assert "competencia" not in names and "uf" not in names  # ficam só no caminho (Hive)
    # arquivo latin-1 decodificado corretamente
    nome = duckdb.sql(f"SELECT any_value(nm_municipio) FROM '{lake.uri(key)}' WHERE cd_municipio = '355030'")
    assert nome.fetchone()[0] == "São Paulo"
    assert pipeline.done_markers(lake, "beneficiarios") == {pipeline._marker(TASKS[2])}


def test_new_version_replaces_marker(env):
    settings, lake = env
    pipeline.run_task(settings, lake, TASKS[5])
    newer = Task(**{**TASKS[5].to_dict(), "version": "v2"})
    pipeline.run_task(settings, lake, newer)
    assert pipeline.done_markers(lake, "igr") == {pipeline._marker(newer)}


def test_gold_end_to_end(env):
    settings, lake = env
    for t in TASKS:
        pipeline.run_task(settings, lake, t)
    out = gold.build(settings, lake)
    assert out["status"] == "built"
    assert out["competencia_ref"] == "2026-07-01"
    assert "tiss_internacoes_mensal" not in out["tables"]  # fonte opcional ausente

    rel = duckdb.sql(f"SELECT * FROM '{lake.uri('gold/painel_operadora/data.parquet')}' ORDER BY registro_ans")
    alfa = dict(zip(rel.columns, rel.fetchone(), strict=True))
    assert alfa["nome"] == "ALFA"
    assert alfa["beneficiarios"] == 30  # (10 + 5) * 2 na competência mais recente
    assert alfa["beneficiarios_12m_antes"] == 15
    assert alfa["variacao_12m_pct"] == 100
    assert alfa["nip_12m"] == 2
    assert alfa["igr"] == 12.5  # prioriza assistência médica
    assert alfa["idss"] == pytest.approx(0.8123)

    manifest = lake.read_json("site/data/manifest.json")
    for entry in manifest["tables"].values():
        assert lake.exists(f"site/data/{entry['file']}")

    # segunda execução sem mudanças na silver não refaz nada
    assert gold.build(settings, lake)["status"] == "skipped"


def test_idss_unpivot(env):
    settings, lake = env
    pipeline.run_task(settings, lake, TASKS[6])
    rows = duckdb.sql(
        f"SELECT indicador, ano_avaliacao, ano_base, valor FROM '{lake.uri('silver/idss/2016_2025.parquet')}' "
        "ORDER BY 1, 2"
    ).fetchall()
    # "ND" é descartado
    assert rows == [("IDQS", 2025, 2024, 0.5), ("IDSS", 2024, 2023, 0.7), ("IDSS", 2025, 2024, 0.8123)]


def test_cadastro_com_varios_snapshots(env):
    """Duas fotos diárias do cadastro não podem duplicar operadoras nem sumir com as canceladas."""
    settings, lake = env
    for t in TASKS:
        pipeline.run_task(settings, lake, t)
    for t in TASKS[:2]:  # mesma foto em outro dia
        dia = {**t.params, "snapshot": "2026-09-17"}
        pipeline.run_task(settings, lake, Task(t.source, f"{dia['situacao']}/2026-09-17", t.url, "v2", dia))
    gold.build(settings, lake, force=True)
    rel = duckdb.sql(
        f"SELECT situacao, count(*), count(DISTINCT registro_ans) FROM '{lake.uri('gold/dim_operadora/data.parquet')}' "
        "GROUP BY 1 ORDER BY 1"
    )
    assert rel.fetchall() == [("ativa", 2, 2), ("cancelada", 1, 1)]

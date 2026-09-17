"""Banco DuckDB para consulta e exploração (SQLTools, DBeaver, CLI do DuckDB).

Não copia dados: cria views sobre os Parquet do lake, organizadas em esquemas e documentadas
com COMMENT ON. Gerado por `ans-bi banco` em data/ans_bi.duckdb (fora do git).

Esquemas:
  gold    marts prontos para análise (o que o painel usa)
  silver  dados tratados, um registro por linha da ANS (particionados por arquivo de origem)
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from .config import Settings
from .pipeline import sql_literal

log = logging.getLogger(__name__)

SILVER = {
    "operadoras": ("silver/operadoras/*/*/data.parquet", "Cadastro de operadoras (ativas e canceladas), foto diária."),
    "beneficiarios_municipio": (
        "silver/beneficiarios_municipio/*/*/data.parquet",
        "Clientes por competência, operadora, município, contratação e cobertura (ICB/ANS).",
    ),
    "beneficiarios_perfil": (
        "silver/beneficiarios_perfil/*/*/data.parquet",
        "Clientes por competência, operadora, UF, sexo e faixa etária (ICB/ANS).",
    ),
    "nip": ("silver/nip/*/data.parquet", "Reclamações de consumidores (NIP), uma linha por demanda."),
    "igr": ("silver/igr/data.parquet", "Índice Geral de Reclamações (IGR) mensal por operadora e cobertura."),
    "idss": ("silver/idss/*.parquet", "Índice de Desempenho da Saúde Suplementar (IDSS) e dimensões, formato longo."),
    "tiss_hospitalar": (
        "silver/tiss_hospitalar/*/*/data.parquet",
        "Internações hospitalares (TISS) agregadas; não identifica a operadora.",
    ),
}  # fmt: skip

GOLD = {
    "dim_operadora": "Dimensão de operadoras: cadastro mais recente, endereço e contato.",
    "painel_operadora": "Uma linha por operadora com os indicadores-chave (clientes, reclamações, IGR, IDSS).",
    "beneficiarios_mensal": "Clientes por competência, operadora, UF, cobertura e tipo de contratação.",
    "mercado_uf_mensal": "Total de clientes e de operadoras por UF e competência.",
    "beneficiarios_municipio_atual": "Clientes por operadora e município na competência mais recente.",
    "perfil_etario": "Clientes por operadora, UF, sexo e faixa etária na competência mais recente.",
    "nip_mensal": "Reclamações por competência, operadora, UF, natureza e assunto.",
    "igr_mensal": "IGR mensal por operadora e cobertura.",
    "idss_indicadores": "IDSS e dimensões (IDQS, IDGA, IDSM, IDGR) por operadora e ano de avaliação.",
    "tiss_internacoes_mensal": "Internações por competência, UF do prestador, modalidade e porte.",
}

# descrições das colunas mais usadas (aparecem no SQLTools/DBeaver)
COLUNAS = {
    "registro_ans": "Código da operadora na ANS (chave de integração entre as tabelas).",
    "competencia": "Mês de referência (primeiro dia do mês).",
    "uf": "Sigla do estado.",
    "cobertura": "Médico-hospitalar ou odontológico.",
    "contratacao": "Individual/familiar, coletivo empresarial, coletivo por adesão.",
    "beneficiarios": "Quantidade de clientes (vínculos ativos).",
    "aderidos": "Novos vínculos no mês (inclui transferências de carteira).",
    "cancelados": "Vínculos cancelados no mês.",
    "demandas": "Quantidade de reclamações (NIP).",
    "igr": "Índice Geral de Reclamações: reclamações por 100 mil clientes. Menor é melhor.",
    "idss": "Índice de Desempenho da Saúde Suplementar (0 a 1). Maior é melhor.",
    "valor": "Valor do indicador.",
    "situacao": "ativa ou cancelada.",
    "uf_sede": "UF da sede da operadora.",
    "pct_resolvidas": "% das reclamações encerradas nos últimos 12 meses resolvidas na mediação (NIP INATIVA/RVE).",
    "nip_12m": "Reclamações NIP nos últimos 12 meses.",
}

CAMINHO_PADRAO = Path("data/ans_bi.duckdb")


def construir(settings: Settings, destino: Path = CAMINHO_PADRAO) -> dict:
    """Recria o arquivo do banco com views apontando para o lake (caminhos absolutos)."""
    if settings.is_s3:
        raise RuntimeError("o banco de exploração usa o lake local; rode com ANS_LAKE_URI apontando para um diretório")
    lake = Path(settings.lake_uri).resolve()
    destino = destino.resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    for arquivo in (destino, destino.with_suffix(destino.suffix + ".wal")):
        arquivo.unlink(missing_ok=True)

    con = duckdb.connect()
    # formato de armazenamento antigo: abre também em ferramentas com versões mais velhas do DuckDB
    con.execute(f"ATTACH {sql_literal(destino)} AS ans_bi (STORAGE_VERSION 'v1.0.0')")
    con.execute("USE ans_bi")
    resumo = {"gold": [], "silver": []}

    con.execute("CREATE SCHEMA gold")
    for tabela, descricao in GOLD.items():
        arquivo = lake / "gold" / tabela / "data.parquet"
        if not arquivo.exists():
            continue
        con.execute(f"CREATE VIEW gold.{tabela} AS SELECT * FROM read_parquet({sql_literal(arquivo)})")
        con.execute(f"COMMENT ON VIEW gold.{tabela} IS {sql_literal(descricao)}")
        resumo["gold"].append(tabela)

    con.execute("CREATE SCHEMA silver")
    for tabela, (padrao, descricao) in SILVER.items():
        if not any(lake.glob(padrao)):
            continue
        con.execute(
            f"CREATE VIEW silver.{tabela} AS SELECT * FROM read_parquet({sql_literal(lake / padrao)}, "
            "hive_partitioning = true, union_by_name = true)"
        )
        con.execute(f"COMMENT ON VIEW silver.{tabela} IS {sql_literal(descricao)}")
        resumo["silver"].append(tabela)

    # comentários de colunas conhecidas
    for esquema, tabelas in resumo.items():
        for tabela in tabelas:
            colunas = {r[0] for r in con.execute(f"DESCRIBE {esquema}.{tabela}").fetchall()}
            for coluna in colunas & COLUNAS.keys():
                con.execute(f"COMMENT ON COLUMN {esquema}.{tabela}.{coluna} IS {sql_literal(COLUNAS[coluna])}")

    con.execute("USE memory")
    con.execute("DETACH ans_bi")
    con.close()
    log.info("banco criado em %s: %s", destino, resumo)
    return {"arquivo": str(destino), **resumo}

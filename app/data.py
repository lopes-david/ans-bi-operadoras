"""Acesso aos marts da gold.

Os Parquet são carregados uma vez em um DuckDB em memória (poucos MB). A origem vem de ANS_GOLD_URI:
  - diretório local com <mart>/data.parquet (padrão: data/lake/gold), ou
  - URL pública (ex.: https://xxxx.cloudfront.net/data), lida via manifest.json.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

MARTS = [
    "dim_operadora",
    "painel_operadora",
    "beneficiarios_mensal",
    "nip_mensal",
    "igr_mensal",
    "idss_indicadores",
]
ROOT = Path(__file__).resolve().parent.parent
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
UF_NOMES = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
    "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}  # fmt: skip


def _sources(uri: str) -> list[tuple[str, str]]:
    if uri.startswith(("http://", "https://")):
        base = uri.rstrip("/")
        with urllib.request.urlopen(f"{base}/manifest.json", timeout=30) as resp:
            manifest = json.load(resp)
        return [(m, f"{base}/{manifest['tables'][m]['file']}") for m in MARTS]
    base = Path(uri) if Path(uri).is_absolute() else ROOT / uri
    files = [(m, str(base / m / "data.parquet")) for m in MARTS]
    missing = [m for m, f in files if not Path(f).exists()]
    if missing:
        raise FileNotFoundError(f"marts ausentes em {base}: {missing}. Rode `make run` para gerar os dados.")
    return files


class Db:
    def __init__(self) -> None:
        self.con = duckdb.connect()
        self.lock = threading.Lock()
        for mart, path in _sources(os.environ.get("ANS_GOLD_URI", "data/lake/gold")):
            self.con.execute(f"CREATE TABLE {mart} AS SELECT * FROM read_parquet(?)", [path])
        self.ref = self.con.execute("SELECT max(competencia) FROM beneficiarios_mensal").fetchone()[0]

    def q(self, sql: str, **params) -> pd.DataFrame:
        with self.lock:  # cada sessão roda numa thread; cada consulta usa seu próprio cursor
            cur = self.con.cursor()
        return cur.execute(sql, params).df()


@st.cache_resource(ttl="1h", show_spinner="Carregando dados da ANS…")
def get_db() -> Db:
    return Db()


def fmt_int(v) -> str:
    return "–" if v is None or pd.isna(v) else f"{v:,.0f}".replace(",", ".")


def fmt_dec(v, casas: int = 1) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_compact(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    for limite, sufixo in ((1e6, " mi"), (1e3, " mil")):
        if abs(v) >= limite:
            return fmt_dec(v / limite, 1) + sufixo
    return fmt_int(v)


def fmt_mes(d) -> str:
    return f"{MESES[d.month - 1]}/{d.year}"


# operadoras "de" um lugar = operadoras com sede ali; clientes = total no Brasil
_SEDES = """
    SELECT p.registro_ans, p.nome, d.cidade, d.uf_sede AS uf, p.beneficiarios AS clientes,
           p.idss, p.igr, p.igr_cobertura
    FROM painel_operadora p JOIN dim_operadora d USING (registro_ans)
    WHERE p.situacao = 'ativa' AND p.beneficiarios > 0
"""

# referência do IGR: mediana das operadoras com 10 mil+ clientes, por tipo de cobertura
_MEDIANAS_IGR = """
    SELECT igr_cobertura, median(igr) AS mediana_igr FROM painel_operadora
    WHERE beneficiarios >= 10000 AND igr IS NOT NULL GROUP BY igr_cobertura
"""


@st.cache_data(ttl="1h")
def sedes_por_estado() -> pd.DataFrame:
    return get_db().q(f"SELECT uf, count(*) AS operadoras, sum(clientes) AS clientes FROM ({_SEDES}) GROUP BY uf")


@st.cache_data(ttl="1h")
def cidades_do_estado(uf: str) -> list[str]:
    df = get_db().q(f"SELECT DISTINCT cidade FROM ({_SEDES}) WHERE uf = $uf AND cidade IS NOT NULL", uf=uf)
    return sorted(df["cidade"], key=lambda c: c.casefold())


@st.cache_data(ttl="1h")
def operadoras_do_estado(uf: str, cidade: str | None = None) -> pd.DataFrame:
    """Operadoras com sede no estado (ou na cidade), com o total de clientes no Brasil, maiores primeiro."""
    return get_db().q(
        f"""SELECT s.registro_ans, s.nome, s.cidade, s.clientes, s.idss, s.igr, m.mediana_igr
            FROM ({_SEDES}) s LEFT JOIN ({_MEDIANAS_IGR}) m USING (igr_cobertura)
            WHERE s.uf = $uf AND ($cidade IS NULL OR s.cidade = $cidade)
            ORDER BY s.clientes DESC""",
        uf=uf, cidade=cidade,
    )  # fmt: skip


@st.cache_data(ttl="1h")
def ficha(reg: str) -> dict:
    """Tudo o que o cartão da operadora mostra."""
    db = get_db()
    cadastro = db.q(
        """SELECT d.*, p.beneficiarios AS clientes_brasil, p.ufs_atuacao, p.igr, p.igr_cobertura, p.idss, p.idss_ano
           FROM dim_operadora d LEFT JOIN painel_operadora p USING (registro_ans)
           WHERE d.registro_ans = $reg""",
        reg=reg,
    ).iloc[0]
    # referência para o IGR: mediana das operadoras com a mesma cobertura
    medianas = db.q(f"SELECT mediana_igr FROM ({_MEDIANAS_IGR}) WHERE igr_cobertura = $cob", cob=cadastro.igr_cobertura)
    mediana_igr = medianas.iloc[0, 0] if len(medianas) else None
    assuntos = db.q(
        """SELECT assunto, sum(demandas) AS reclamacoes FROM nip_mensal
           WHERE registro_ans = $reg
             AND competencia > (SELECT max(competencia) FROM beneficiarios_mensal) - INTERVAL 12 MONTH
           GROUP BY assunto ORDER BY reclamacoes DESC LIMIT 5""",
        reg=reg,
    )
    return {"cadastro": cadastro, "mediana_igr": mediana_igr, "assuntos": assuntos}


@st.cache_data(ttl="1h")
def evolucao_operadora(reg: str, cobertura_igr: str | None) -> dict:
    """Séries e resumos que a ficha mostra além da foto atual (sempre pela chave da operadora)."""
    db = get_db()
    ref = "(SELECT max(competencia) FROM beneficiarios_mensal)"
    clientes = db.q(
        "SELECT competencia, sum(beneficiarios) AS valor FROM beneficiarios_mensal "
        "WHERE registro_ans = $reg GROUP BY competencia ORDER BY competencia",
        reg=reg,
    )
    fluxo = db.q(
        f"""SELECT sum(aderidos) AS entraram, sum(cancelados) AS sairam FROM beneficiarios_mensal
            WHERE registro_ans = $reg AND competencia > {ref} - INTERVAL 12 MONTH AND competencia <= {ref}""",
        reg=reg,
    ).iloc[0]
    contratacao = db.q(
        f"""SELECT contratacao, sum(beneficiarios) AS clientes FROM beneficiarios_mensal
            WHERE registro_ans = $reg AND competencia = {ref}
            GROUP BY contratacao HAVING sum(beneficiarios) > 0 ORDER BY clientes DESC""",
        reg=reg,
    )
    reclamacoes = db.q(
        f"""SELECT competencia, sum(demandas) AS valor FROM nip_mensal
            WHERE registro_ans = $reg AND competencia > {ref} - INTERVAL 24 MONTH AND competencia <= {ref}
            GROUP BY competencia ORDER BY competencia""",
        reg=reg,
    )
    igr = db.q(
        """SELECT competencia, igr AS valor FROM igr_mensal
           WHERE registro_ans = $reg AND cobertura = $cob AND igr IS NOT NULL
             AND competencia > (SELECT max(competencia) FROM igr_mensal) - INTERVAL 36 MONTH
           ORDER BY competencia""",
        reg=reg, cob=cobertura_igr,
    )  # fmt: skip
    idss = db.q(
        "SELECT ano_avaliacao AS ano, valor FROM idss_indicadores "
        "WHERE registro_ans = $reg AND indicador = 'IDSS' ORDER BY ano_avaliacao",
        reg=reg,
    )
    partes_idss = db.q(
        """SELECT indicador, valor FROM idss_indicadores
           WHERE registro_ans = $reg AND indicador <> 'IDSS'
             AND ano_avaliacao = (SELECT max(ano_avaliacao) FROM idss_indicadores WHERE registro_ans = $reg)""",
        reg=reg,
    )
    return {
        "clientes": clientes,
        "entraram": fluxo.entraram,
        "sairam": fluxo.sairam,
        "contratacao": contratacao,
        "reclamacoes": reclamacoes,
        "igr": igr,
        "idss": idss,
        "partes_idss": dict(zip(partes_idss["indicador"], partes_idss["valor"], strict=True)),
    }

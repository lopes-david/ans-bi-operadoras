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

# referência do IGR por tipo de cobertura, entre operadoras com 10 mil+ clientes: a mediana; quando ela é zero
# (nas odontológicas a maioria tem IGR 0), a média, para ainda haver com o que comparar
_MEDIANAS_IGR = """
    SELECT igr_cobertura,
           CASE WHEN median(igr) > 0 THEN median(igr) ELSE avg(igr) END AS mediana_igr
    FROM painel_operadora
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
        """SELECT d.*, p.beneficiarios AS clientes_brasil, p.ufs_atuacao, p.igr, p.igr_cobertura, p.idss, p.idss_ano,
                  p.pct_resolvidas, p.nip_resolvidas_12m, p.nip_avaliadas_12m
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
           GROUP BY assunto ORDER BY reclamacoes DESC""",
        reg=reg,
    )
    return {"cadastro": cadastro, "mediana_igr": mediana_igr, "assuntos": assuntos}


@st.cache_data(ttl="1h")
def evolucao_operadora(reg: str, cobertura_igr: str | None) -> dict:
    """Séries e resumos que a ficha mostra além da foto atual (sempre pela chave da operadora)."""
    db = get_db()
    ref = "(SELECT max(competencia) FROM beneficiarios_mensal)"
    saltos = _saltos(reg)
    # meses de transferência de carteira ficam fora: a ANS conta os clientes transferidos como "entradas"
    meses_transferencia = [pd.Timestamp(x["competencia"]).date() for x in saltos] or [pd.Timestamp("1900-01-01").date()]
    fluxo = db.q(
        f"""SELECT sum(aderidos) AS entraram, sum(cancelados) AS sairam FROM beneficiarios_mensal
            WHERE registro_ans = $reg AND competencia > {ref} - INTERVAL 12 MONTH AND competencia <= {ref}
              AND NOT list_contains($fora, competencia)""",
        reg=reg, fora=meses_transferencia,
    ).iloc[0]  # fmt: skip
    transferencia_12m = next(
        (
            x
            for x in reversed(saltos)
            if pd.Timestamp(x["competencia"]) > pd.Timestamp(db.ref) - pd.DateOffset(months=12)
        ),
        None,
    )
    # séries por trimestre (menos oscilação que o mês a mês): clientes no fim do trimestre, IGR médio
    clientes_tri = db.q(
        """SELECT date_trunc('quarter', competencia) AS competencia, arg_max(valor, mes) AS valor, max(mes) AS ate
           FROM (SELECT competencia AS mes, competencia, sum(beneficiarios) AS valor FROM beneficiarios_mensal
                 WHERE registro_ans = $reg GROUP BY competencia)
           GROUP BY 1 ORDER BY 1""",
        reg=reg,
    )
    igr_tri = db.q(
        """SELECT date_trunc('quarter', competencia) AS competencia, avg(igr) AS valor, max(competencia) AS ate
           FROM igr_mensal
           WHERE registro_ans = $reg AND cobertura = $cob AND igr IS NOT NULL
             AND competencia >= (SELECT min(competencia) FROM beneficiarios_mensal)
           GROUP BY 1 ORDER BY 1""",
        reg=reg, cob=cobertura_igr,
    )  # fmt: skip
    # por ano: clientes no último mês de cada ano e IGR médio do ano
    clientes_ano = db.q(
        """SELECT year(competencia) AS ano, arg_max(valor, competencia) AS valor, max(competencia) AS ate
           FROM (SELECT competencia, sum(beneficiarios) AS valor FROM beneficiarios_mensal
                 WHERE registro_ans = $reg GROUP BY competencia)
           GROUP BY 1 ORDER BY 1""",
        reg=reg,
    )
    igr_ano = db.q(
        """SELECT year(competencia) AS ano, avg(igr) AS valor, max(competencia) AS ate
           FROM igr_mensal
           WHERE registro_ans = $reg AND cobertura = $cob AND igr IS NOT NULL
             AND competencia >= (SELECT min(competencia) FROM beneficiarios_mensal)
           GROUP BY 1 ORDER BY 1""",
        reg=reg, cob=cobertura_igr,
    )  # fmt: skip
    contratacao = db.q(
        f"""SELECT contratacao, sum(beneficiarios) AS clientes FROM beneficiarios_mensal
            WHERE registro_ans = $reg AND competencia = {ref}
            GROUP BY contratacao HAVING sum(beneficiarios) > 0 ORDER BY clientes DESC""",
        reg=reg,
    )
    idss = db.q(
        "SELECT ano_avaliacao AS ano, valor FROM idss_indicadores "
        "WHERE registro_ans = $reg AND indicador = 'IDSS' ORDER BY ano_avaliacao",
        reg=reg,
    )
    # as 4 partes do IDSS, ano a ano (a ANS só publica as partes a partir de 2016)
    temas_idss = db.q(
        """SELECT ano_avaliacao AS ano, indicador, valor FROM idss_indicadores
           WHERE registro_ans = $reg AND indicador <> 'IDSS' ORDER BY ano_avaliacao""",
        reg=reg,
    )
    return {
        "clientes_tri": clientes_tri,
        "igr_tri": igr_tri,
        "clientes_ano": clientes_ano,
        "igr_ano": igr_ano,
        "transferencia_12m": transferencia_12m,
        "saltos": saltos,
        "entraram": fluxo.entraram,
        "sairam": fluxo.sairam,
        "contratacao": contratacao,
        "idss": idss,
        "temas_idss": temas_idss,
    }


SALTO_MINIMO = 5000  # clientes


@st.cache_data(ttl="1h")
def _saltos(reg: str) -> list[dict]:
    """Mudanças bruscas de carteira num único mês (normalmente transferência entre empresas do mesmo grupo).

    Considera salto uma variação de pelo menos 5 mil clientes e 30% do maior valor entre antes e depois
    (ex.: dobrar de tamanho ou perder quase tudo num mês). Quando outra operadora
    teve a variação oposta no mesmo mês, ela é apontada como origem/destino.
    """
    return get_db().q(
        """
        WITH mensal AS (
            SELECT registro_ans, competencia, sum(beneficiarios) AS v
            FROM beneficiarios_mensal GROUP BY ALL
        ),
        dif AS (
            SELECT registro_ans, competencia, v,
                   lag(v) OVER (PARTITION BY registro_ans ORDER BY competencia) AS antes
            FROM mensal
        ),
        saltos AS (
            SELECT *, v - antes AS variacao FROM dif
            WHERE antes IS NOT NULL AND abs(v - antes) >= $minimo AND abs(v - antes) >= 0.3 * greatest(antes, v)
        )
        SELECT s.competencia, s.antes, s.v AS depois, s.variacao,
               (SELECT p.nome FROM saltos o JOIN painel_operadora p USING (registro_ans)
                WHERE o.competencia = s.competencia AND o.registro_ans <> s.registro_ans
                  AND sign(o.variacao) = -sign(s.variacao) AND abs(o.variacao) >= 0.5 * abs(s.variacao)
                ORDER BY abs(abs(o.variacao) - abs(s.variacao)) LIMIT 1) AS contraparte
        FROM saltos s
        WHERE s.registro_ans = $reg
        ORDER BY s.competencia
        """,
        reg=reg, minimo=SALTO_MINIMO,
    ).to_dict("records")  # fmt: skip

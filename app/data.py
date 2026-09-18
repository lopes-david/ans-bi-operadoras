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
    "mercado_uf_mensal",
    "perfil_etario",
    "beneficiarios_municipio_atual",
]
# o TISS é opcional: nem todo lake tem (a base é grande e nenhuma tela de operadora usa)
MARTS_OPCIONAIS = ["tiss_internacoes_mensal"]
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
        tabelas = manifest["tables"]
        return [(m, f"{base}/{tabelas[m]['file']}") for m in [*MARTS, *MARTS_OPCIONAIS] if m in tabelas]
    base = Path(uri) if Path(uri).is_absolute() else ROOT / uri
    files = [(m, str(base / m / "data.parquet")) for m in MARTS]
    missing = [m for m, f in files if not Path(f).exists()]
    if missing:
        raise FileNotFoundError(f"marts ausentes em {base}: {missing}. Rode `make run` para gerar os dados.")
    opcionais = [(m, str(base / m / "data.parquet")) for m in MARTS_OPCIONAIS]
    return files + [(m, f) for m, f in opcionais if Path(f).exists()]


class Db:
    def __init__(self) -> None:
        self.con = duckdb.connect()
        self.lock = threading.Lock()
        self.tabelas = set()
        for mart, path in _sources(os.environ.get("ANS_GOLD_URI", "data/lake/gold")):
            self.con.execute(f"CREATE TABLE {mart} AS SELECT * FROM read_parquet(?)", [path])
            self.tabelas.add(mart)
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


# as faixas do cadastro de clientes (ICB) e das internações (TISS) são diferentes; estes 5 grupos
# existem nas duas bases e permitem cruzar "quem tem plano" com "quem interna"
FAIXAS_CLIENTES = """
    CASE
        WHEN faixa_etaria IN ('Menos de 1 ano', '1 a 4 anos', '5 a 9 anos', '10 a 14 anos') THEN '0 a 14'
        WHEN faixa_etaria IN ('15 a 17 anos', '18 a 19 anos', '20 a 24 anos', '25 a 29 anos') THEN '15 a 29'
        WHEN faixa_etaria IN ('30 a 34 anos', '35 a 39 anos', '40 a 44 anos', '45 a 49 anos') THEN '30 a 49'
        WHEN faixa_etaria IN ('50 a 54 anos', '55 a 59 anos', '60 a 64 anos', '65 a 69 anos') THEN '50 a 69'
        WHEN faixa_etaria IN ('70 a 74 anos', '75 a 79 anos', '80 anos ou mais') THEN '70 ou mais'
    END
"""
FAIXAS_TISS = """
    CASE
        WHEN faixa_etaria IN ('Menos de 1 ano', '1 a 4 anos', '5 a 9 anos', '10 a 14 anos') THEN '0 a 14'
        WHEN faixa_etaria IN ('15 a 19 anos', '20 a 29 anos') THEN '15 a 29'
        WHEN faixa_etaria IN ('30 a 39 anos', '40 a 49 anos') THEN '30 a 49'
        WHEN faixa_etaria IN ('50 a 59 anos', '60 a 69 anos') THEN '50 a 69'
        WHEN faixa_etaria IN ('70 a 79 anos', '80 anos ou mais') THEN '70 ou mais'
    END
"""


def tem_internacoes() -> bool:
    return "tiss_internacoes_mensal" in get_db().tabelas


@st.cache_data(ttl="1h")
def ano_das_internacoes() -> int | None:
    """Último ano completo publicado no TISS (a base sai com atraso)."""
    if not tem_internacoes():
        return None
    return get_db().q("SELECT max(year(competencia)) AS ano FROM tiss_internacoes_mensal").iloc[0]["ano"]


@st.cache_data(ttl="1h")
def estados_internacoes() -> pd.DataFrame:
    """Uma linha por estado: internações, tempo de permanência, UTI e reclamações, sempre por 100 mil clientes.

    Dividir pelo número de clientes é o que torna estados de tamanhos diferentes comparáveis.
    """
    ano = ano_das_internacoes()
    if ano is None:
        return pd.DataFrame()
    return get_db().q(
        """
        WITH clientes AS (
            SELECT uf, sum(beneficiarios) AS clientes FROM mercado_uf_mensal
            WHERE competencia = (SELECT max(competencia) FROM mercado_uf_mensal) GROUP BY uf
        ),
        internacoes AS (
            SELECT uf, sum(internacoes) AS internacoes, sum(dias_permanencia) AS dias, sum(diarias_uti) AS uti
            FROM tiss_internacoes_mensal WHERE year(competencia) = $ano GROUP BY uf
        ),
        reclamacoes AS (
            SELECT uf, sum(demandas) AS reclamacoes FROM nip_mensal
            WHERE competencia > (SELECT max(competencia) FROM nip_mensal) - INTERVAL 12 MONTH GROUP BY uf
        )
        SELECT uf, clientes, internacoes, dias, uti, coalesce(reclamacoes, 0) AS reclamacoes,
               100000.0 * internacoes / clientes          AS internacoes_100mil,
               dias * 1.0 / nullif(internacoes, 0)        AS dias_por_internacao,
               100.0 * uti / nullif(dias, 0)              AS pct_uti,
               100000.0 * reclamacoes / clientes          AS reclamacoes_100mil
        FROM clientes JOIN internacoes USING (uf) LEFT JOIN reclamacoes USING (uf)
        ORDER BY internacoes_100mil DESC
        """,
        ano=int(ano),
    )


# ponto médio de cada faixa do TISS, para estimar a idade média de quem interna
IDADE_MEDIA_TISS = """
    CASE faixa_etaria
        WHEN 'Menos de 1 ano' THEN 0.5 WHEN '1 a 4 anos' THEN 3 WHEN '5 a 9 anos' THEN 7
        WHEN '10 a 14 anos' THEN 12 WHEN '15 a 19 anos' THEN 17 WHEN '20 a 29 anos' THEN 25
        WHEN '30 a 39 anos' THEN 35 WHEN '40 a 49 anos' THEN 45 WHEN '50 a 59 anos' THEN 55
        WHEN '60 a 69 anos' THEN 65 WHEN '70 a 79 anos' THEN 75 WHEN '80 anos ou mais' THEN 85
    END
"""
TIPOS_INTERNACAO = {"1": "Clínica", "2": "Cirúrgica", "3": "Obstétrica", "4": "Pediátrica", "5": "Psiquiátrica"}


@st.cache_data(ttl="1h")
def perfil_das_internacoes(uf: str | None = None) -> dict:
    """Tipo de internação, urgência e idade média de quem interna (no país ou em um estado)."""
    ano = ano_das_internacoes()
    if ano is None:
        return {}
    db, filtro = get_db(), ("AND uf = $uf" if uf else "")
    params = {"ano": int(ano), "uf": uf} if uf else {"ano": int(ano)}
    tipos = db.q(
        f"""SELECT tipo_internacao AS tipo, sum(internacoes) AS internacoes FROM tiss_internacoes_mensal
            WHERE year(competencia) = $ano {filtro} AND tipo_internacao IS NOT NULL
            GROUP BY 1 ORDER BY internacoes DESC""",
        **params,
    )
    resumo = db.q(
        f"""SELECT sum(internacoes) FILTER (carater_atendimento = '2') AS urgencia,
                   sum(internacoes)                                    AS total,
                   sum(internacoes * {IDADE_MEDIA_TISS}) / sum(internacoes)
                       FILTER ({IDADE_MEDIA_TISS} IS NOT NULL)          AS idade_media
            FROM tiss_internacoes_mensal WHERE year(competencia) = $ano {filtro}""",
        **params,
    ).iloc[0]
    tipos = tipos.assign(tipo=tipos["tipo"].map(lambda t: TIPOS_INTERNACAO.get(t, "Outras")))
    return {"tipos": tipos, "urgencia": resumo.urgencia, "total": resumo.total, "idade_media": resumo.idade_media}


@st.cache_data(ttl="1h")
def idade_media_por_estado() -> pd.DataFrame:
    """Idade média estimada de quem interna e fatia de clientes com 70+ anos, por estado."""
    ano = ano_das_internacoes()
    if ano is None:
        return pd.DataFrame()
    return get_db().q(
        f"""
        WITH internados AS (
            SELECT uf, sum(internacoes * {IDADE_MEDIA_TISS}) / sum(internacoes)
                        FILTER ({IDADE_MEDIA_TISS} IS NOT NULL) AS idade_media
            FROM tiss_internacoes_mensal WHERE year(competencia) = $ano GROUP BY uf
        ),
        idosos AS (
            SELECT uf, 100.0 * sum(beneficiarios) FILTER ({FAIXAS_CLIENTES} = '70 ou mais') / sum(beneficiarios)
                       AS pct_idosos
            FROM perfil_etario GROUP BY uf
        )
        SELECT uf, idade_media, pct_idosos FROM internados JOIN idosos USING (uf)
        """,
        ano=int(ano),
    )


@st.cache_data(ttl="1h")
def internacoes_por_idade(uf: str | None = None) -> pd.DataFrame:
    """Clientes e internações nas mesmas faixas de idade, com a taxa de internação de cada uma."""
    ano = ano_das_internacoes()
    if ano is None:
        return pd.DataFrame()
    filtro_uf = "AND uf = $uf" if uf else ""
    return get_db().q(
        f"""
        WITH clientes AS (
            SELECT {FAIXAS_CLIENTES} AS faixa, sum(beneficiarios) AS clientes
            FROM perfil_etario WHERE true {filtro_uf} GROUP BY 1
        ),
        internacoes AS (
            SELECT {FAIXAS_TISS} AS faixa, sum(internacoes) AS internacoes,
                   sum(dias_permanencia) AS dias
            FROM tiss_internacoes_mensal WHERE year(competencia) = $ano {filtro_uf} GROUP BY 1
        )
        SELECT faixa, clientes, internacoes,
               100.0 * internacoes / nullif(clientes, 0) AS por_100_clientes,
               dias * 1.0 / nullif(internacoes, 0)       AS dias_por_internacao
        FROM clientes JOIN internacoes USING (faixa) WHERE faixa IS NOT NULL ORDER BY faixa
        """,
        **({"ano": int(ano), "uf": uf} if uf else {"ano": int(ano)}),  # DuckDB recusa parâmetro não usado
    )


@st.cache_data(ttl="1h")
def mercado_por_estado() -> pd.DataFrame:
    """Pessoas com plano em cada estado (onde moram, não onde a operadora tem sede)."""
    return get_db().q(
        """SELECT uf, sum(beneficiarios) AS clientes FROM mercado_uf_mensal
           WHERE competencia = (SELECT max(competencia) FROM mercado_uf_mensal) GROUP BY uf"""
    )


@st.cache_data(ttl="1h")
def series_do_estado(uf: str) -> dict:
    """Séries trimestrais do próprio estado: internações e reclamações."""
    db = get_db()
    internacoes = pd.DataFrame()
    if tem_internacoes():
        internacoes = db.q(
            """SELECT date_trunc('quarter', competencia) AS competencia, sum(internacoes) AS valor,
                      max(competencia) AS ate
               FROM tiss_internacoes_mensal WHERE uf = $uf GROUP BY 1 ORDER BY 1""",
            uf=uf,
        )
    reclamacoes = db.q(
        """SELECT date_trunc('quarter', competencia) AS competencia, sum(demandas) AS valor, max(competencia) AS ate
           FROM nip_mensal WHERE uf = $uf AND competencia >= (SELECT max(competencia) FROM nip_mensal)
                                              - INTERVAL 3 YEAR
           GROUP BY 1 ORDER BY 1""",
        uf=uf,
    )
    clientes_ano = db.q(
        """SELECT year(competencia) AS ano, arg_max(valor, mes) AS valor, max(mes) AS ate
           FROM (SELECT competencia AS mes, competencia, sum(beneficiarios) AS valor
                 FROM mercado_uf_mensal WHERE uf = $uf GROUP BY competencia)
           GROUP BY 1 ORDER BY 1""",
        uf=uf,
    )
    contratacao = db.q(
        """SELECT contratacao, sum(beneficiarios) AS clientes FROM beneficiarios_mensal
           WHERE uf = $uf AND competencia = (SELECT max(competencia) FROM beneficiarios_mensal)
           GROUP BY 1 HAVING sum(beneficiarios) > 0 ORDER BY clientes DESC""",
        uf=uf,
    )
    return {"internacoes": internacoes, "reclamacoes": reclamacoes, "clientes_ano": clientes_ano,
            "contratacao": contratacao}  # fmt: skip


@st.cache_data(ttl="1h")
def tempo_por_tipo(uf: str) -> pd.DataFrame:
    """Quanto dura cada tipo de internação no estado (clínica, cirúrgica...)."""
    ano = ano_das_internacoes()
    if ano is None:
        return pd.DataFrame()
    tipos = get_db().q(
        """SELECT tipo_internacao AS tipo, sum(internacoes) AS internacoes,
                  sum(dias_permanencia) * 1.0 / nullif(sum(internacoes), 0) AS valor
           FROM tiss_internacoes_mensal
           WHERE uf = $uf AND year(competencia) = $ano AND tipo_internacao IS NOT NULL
           GROUP BY 1 ORDER BY internacoes DESC""",
        uf=uf, ano=int(ano),
    )  # fmt: skip
    return tipos.assign(tipo=tipos["tipo"].map(lambda t: TIPOS_INTERNACAO.get(t, "Outras")))


@st.cache_data(ttl="1h")
def comparativo_idade(uf: str) -> pd.DataFrame:
    """Taxa de internação por faixa de idade no estado e no Brasil, para ver onde ele foge da média."""
    estado, pais = internacoes_por_idade(uf), internacoes_por_idade()
    if estado.empty or pais.empty:
        return pd.DataFrame()
    return pd.concat([
        estado.assign(serie="Aqui", valor=estado["por_100_clientes"]),
        pais.assign(serie="Brasil", valor=pais["por_100_clientes"]),
    ])[["faixa", "serie", "valor"]]  # fmt: skip


@st.cache_data(ttl="1h")
def panorama_estado(uf: str) -> dict:
    """Retrato do estado, somando todas as operadoras: mercado, quem tem plano, internações e reclamações.

    São os dados que não fazem sentido por operadora (perfil etário, internações do TISS) ou que só
    ganham significado somados (mercado, municípios).
    """
    db = get_db()
    ref = "(SELECT max(competencia) FROM mercado_uf_mensal)"
    mercado = db.q(
        f"""SELECT sum(beneficiarios) FILTER (cobertura = 'Médico-hospitalar') AS medico,
                   sum(beneficiarios) FILTER (cobertura = 'Odontológico')      AS odonto
            FROM mercado_uf_mensal WHERE uf = $uf AND competencia = {ref}""",
        uf=uf,
    ).iloc[0]
    # quem tem as duas coberturas conta uma vez só (por isso não dá para somar a coluna operadoras)
    operadoras = db.q(
        """SELECT count(DISTINCT registro_ans) AS n FROM beneficiarios_mensal
           WHERE uf = $uf AND beneficiarios > 0
             AND competencia = (SELECT max(competencia) FROM beneficiarios_mensal)""",
        uf=uf,
    ).iloc[0]["n"]
    antes = db.q(
        f"""SELECT sum(beneficiarios) AS total FROM mercado_uf_mensal
            WHERE uf = $uf AND competencia = {ref} - INTERVAL 12 MONTH""",
        uf=uf,
    ).iloc[0]
    serie_tri = db.q(
        """SELECT date_trunc('quarter', competencia) AS competencia, arg_max(valor, mes) AS valor, max(mes) AS ate
           FROM (SELECT competencia AS mes, competencia, sum(beneficiarios) AS valor
                 FROM mercado_uf_mensal WHERE uf = $uf GROUP BY competencia)
           GROUP BY 1 ORDER BY 1""",
        uf=uf,
    )
    maiores = db.q(
        """SELECT p.nome, sum(b.beneficiarios) AS clientes
           FROM beneficiarios_mensal b JOIN painel_operadora p USING (registro_ans)
           WHERE b.uf = $uf AND b.competencia = (SELECT max(competencia) FROM beneficiarios_mensal)
           GROUP BY 1 HAVING sum(b.beneficiarios) > 0 ORDER BY clientes DESC LIMIT 5""",
        uf=uf,
    )
    faixas = db.q(
        f"""SELECT {FAIXAS_CLIENTES} AS faixa, sum(beneficiarios) AS clientes FROM perfil_etario
            WHERE uf = $uf GROUP BY 1 HAVING faixa IS NOT NULL ORDER BY 1""",
        uf=uf,
    )
    sexo = db.q(
        "SELECT sexo, sum(beneficiarios) AS clientes FROM perfil_etario WHERE uf = $uf GROUP BY 1",
        uf=uf,
    )
    cidades = db.q(
        """SELECT municipio, sum(beneficiarios) AS clientes FROM beneficiarios_municipio_atual
           WHERE uf = $uf GROUP BY 1 ORDER BY clientes DESC LIMIT 5""",
        uf=uf,
    )
    municipios = db.q(
        "SELECT count(DISTINCT cd_municipio) AS n FROM beneficiarios_municipio_atual WHERE uf = $uf", uf=uf
    ).iloc[0]["n"]
    if "tiss_internacoes_mensal" in db.tabelas:
        internacoes = db.q(
            """SELECT year(competencia) AS ano, sum(internacoes) AS valor, sum(dias_permanencia) AS dias,
                      sum(diarias_uti) AS uti
               FROM tiss_internacoes_mensal WHERE uf = $uf GROUP BY 1 ORDER BY 1""",
            uf=uf,
        )
    else:
        internacoes = pd.DataFrame(columns=["ano", "valor", "dias", "uti"])
    nip_ref = "(SELECT max(competencia) FROM nip_mensal)"
    natureza = db.q(
        f"""SELECT natureza, sum(demandas) AS demandas FROM nip_mensal
            WHERE uf = $uf AND competencia > {nip_ref} - INTERVAL 12 MONTH
            GROUP BY 1 ORDER BY demandas DESC""",
        uf=uf,
    )
    assuntos = db.q(
        f"""SELECT assunto, sum(demandas) AS reclamacoes FROM nip_mensal
            WHERE uf = $uf AND competencia > {nip_ref} - INTERVAL 12 MONTH
            GROUP BY 1 ORDER BY reclamacoes DESC""",
        uf=uf,
    )
    total = (mercado.medico or 0) + (mercado.odonto or 0)
    return {
        "clientes": total,
        "medico": mercado.medico,
        "odonto": mercado.odonto,
        "operadoras": operadoras,
        "variacao_12m": (100 * (total - antes.total) / antes.total) if antes.total else None,
        "serie_tri": serie_tri,
        "maiores": maiores,
        "faixas": faixas,
        "sexo": dict(zip(sexo["sexo"], sexo["clientes"], strict=True)),
        "cidades": cidades,
        "municipios": municipios,
        "internacoes": internacoes,
        "natureza": natureza,
        "assuntos": assuntos,
    }

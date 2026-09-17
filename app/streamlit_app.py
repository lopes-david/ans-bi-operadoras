"""Planos de saúde no Brasil: escolha um estado no mapa e veja as operadoras.

Rodar: `make app` (ou `uv run --group app streamlit run app/streamlit_app.py`).
"""

import pandas as pd
import streamlit as st

from classificacao import (
    QUALIDADE,
    RECLAMACOES,
    RECLAMACOES_CURTO,
    SEM_INDICE,
    SEM_NOTA,
    grupo_reclamacoes,
    qualidade,
    reclamacoes,
)
from componentes.mapa import mapa_brasil
from data import (
    UF_NOMES,
    cidades_do_estado,
    fmt_compact,
    fmt_int,
    fmt_mes,
    get_db,
    operadoras_do_estado,
    sedes_por_estado,
)
from ficha_operadora import abrir_ficha

st.set_page_config(page_title="ANS BI · Planos de saúde", page_icon="🩺", layout="wide")

ORDENS = {
    "clientes": "Mais clientes",
    "melhor_qualidade": "Melhor qualidade",
    "pior_qualidade": "Pior qualidade",
    "menos_reclamacoes": "Menos reclamações",
    "mais_reclamacoes": "Mais reclamações",
}


def preparar_lista(ops: pd.DataFrame, ordem: str, filtro_qualidade: list, filtro_reclamacoes: list, busca: str):
    """Aplica a leitura em palavras, os filtros e a ordenação escolhidos no painel."""
    df = ops.copy()
    df["qualidade"] = df["idss"].map(lambda v: (qualidade(v) or (SEM_NOTA,))[0])
    df["_reclamacoes"] = [
        (reclamacoes(i, m) or (SEM_INDICE,))[0] for i, m in zip(df["igr"], df["mediana_igr"], strict=True)
    ]
    df["reclamacoes"] = df["_reclamacoes"].map(lambda t: RECLAMACOES_CURTO.get(t, t))
    df["_proporcao"] = df["igr"] / df["mediana_igr"]  # compara operadoras de coberturas diferentes
    if filtro_qualidade:
        df = df[df["qualidade"].isin(filtro_qualidade)]
    if filtro_reclamacoes:
        df = df[df["_reclamacoes"].map(grupo_reclamacoes).isin(filtro_reclamacoes)]
    if busca:
        df = df[df["nome"].str.contains(busca, case=False, na=False, regex=False)]
    coluna, crescente = {
        "clientes": ("clientes", False),
        "melhor_qualidade": ("idss", False),
        "pior_qualidade": ("idss", True),
        "menos_reclamacoes": ("_proporcao", True),
        "mais_reclamacoes": ("_proporcao", False),
    }[ordem]
    return df.sort_values(coluna, ascending=crescente, na_position="last").reset_index(drop=True)


# o painel lateral entra deslizando sempre que um estado novo é escolhido
st.html(
    """<style>
    /* tela inicial cabe inteira na janela: sem rolagem da página */
    .block-container { padding-top: 1.25rem !important; padding-bottom: 0.5rem !important; }
    [data-testid="stHeader"] { background: transparent; }
    h1 { font-size: 1.9rem !important; padding: 0.25rem 0 0 !important; }
    [class*="st-key-painel-"] { max-height: calc(100vh - 130px); overflow-y: auto; }
    [class*="st-key-painel-"] { animation: entrar .45s cubic-bezier(.2,.9,.25,1); }
    @keyframes entrar { from { transform: translateX(24px); } }
    @media (prefers-reduced-motion: reduce) { [class*="st-key-painel-"] { animation: none; } }
    </style>"""
)

db = get_db()
por_estado = sedes_por_estado().set_index("uf")

# --- estado escolhido <-> URL (?uf=RS) --------------------------------------------------------
if "uf" not in st.session_state:
    st.session_state["uf"] = st.query_params.get("uf") if st.query_params.get("uf") in UF_NOMES else None


def atualizar_url():
    uf = st.session_state.get("uf")
    if uf:
        st.query_params["uf"] = uf
    else:
        st.query_params.pop("uf", None)


def ao_clicar_no_mapa():
    evento = st.session_state["mapa"]
    clique = evento.get("clique") if hasattr(evento, "get") else getattr(evento, "clique", None)
    if clique is not None:
        st.session_state["uf"] = clique.get("uf")
        atualizar_url()


def ao_escolher_operadora():
    tabela = st.session_state[st.session_state["_tabela_atual"]]
    if tabela.selection.rows:
        linha = st.session_state["_lista_atual"].iloc[tabela.selection.rows[0]]
        st.session_state["_abrir"] = linha["registro_ans"]
        # nova chave = seleção limpa; assim o mesmo item pode ser aberto de novo
        st.session_state["_versao_lista"] = st.session_state.get("_versao_lista", 0) + 1


def limpar_estado():
    st.session_state["uf"] = None
    atualizar_url()


uf = st.session_state["uf"]

# --- tela ---------------------------------------------------------------------------------------
titulo, escolha = st.columns([3, 1], vertical_alignment="bottom")
with titulo:
    st.title("Planos de saúde no Brasil", anchor=False)
    st.caption(f"Clique em um estado para ver as operadoras com sede nele · dados da ANS de {fmt_mes(db.ref)}")
escolha.selectbox(
    "Estado",
    [None, *sorted(UF_NOMES, key=UF_NOMES.get)],
    format_func=lambda s: "Escolha na lista…" if s is None else UF_NOMES[s],
    key="uf",
    on_change=atualizar_url,
)

col_mapa, col_lado = st.columns([1, 1], gap="large")

with col_mapa:
    valores = {
        sigla: (
            {
                "nome": nome,
                "valor": int(por_estado.at[sigla, "operadoras"]),
                "texto": f"{fmt_int(por_estado.at[sigla, 'operadoras'])} operadoras com sede aqui",
            }
            if sigla in por_estado.index
            else {"nome": nome, "valor": 0, "texto": "nenhuma operadora com sede aqui"}
        )
        for sigla, nome in UF_NOMES.items()
    }
    mapa_brasil(valores, uf, key="mapa", on_clique=ao_clicar_no_mapa)

with col_lado:
    if not uf:
        with st.container(border=True, key="painel-brasil"):
            st.subheader("Escolha um estado", anchor=False)
            st.write("Clique em um estado no mapa para ver as operadoras de planos de saúde que têm sede lá.")
            a, b = st.columns(2)
            a.metric("Operadoras", fmt_int(por_estado["operadoras"].sum()))
            b.metric("Clientes no Brasil", fmt_compact(por_estado["clientes"].sum()))
    else:
        with st.container(border=True, key=f"painel-{uf}"):
            topo, fechar = st.columns([5, 1], vertical_alignment="center")
            topo.subheader(UF_NOMES[uf], anchor=False)
            fechar.button("", icon=":material/close:", on_click=limpar_estado, help="Voltar ao Brasil",
                          key="fechar", width="stretch")  # fmt: skip

            c1, c2 = st.columns(2)
            cidade = c1.selectbox("Cidade da sede", [None, *cidades_do_estado(uf)], key=f"cidade-{uf}",
                                  format_func=lambda c: "Todas as cidades" if c is None else c)  # fmt: skip
            ordem = c2.selectbox("Ordenar por", list(ORDENS), format_func=ORDENS.get, key="ordem")
            c3, c4 = st.columns(2)
            f_qualidade = c3.multiselect("Qualidade (IDSS)", QUALIDADE, key="f_qualidade", placeholder="Todas")
            f_reclamacoes = c4.multiselect("Reclamações (IGR)", RECLAMACOES, key="f_reclamacoes", placeholder="Todas")
            busca = st.text_input("Buscar operadora", placeholder="Buscar operadora pelo nome…", key=f"busca-{uf}",
                                  label_visibility="collapsed")  # fmt: skip
            onde = cidade or UF_NOMES[uf]

            ops = operadoras_do_estado(uf, cidade)
            lista = preparar_lista(ops, ordem, f_qualidade, f_reclamacoes, busca)
            st.markdown(f"**{fmt_int(len(lista))}** operadoras com sede em {onde} · "
                        f"**{fmt_compact(lista['clientes'].sum())}** clientes no Brasil")  # fmt: skip

            filtros = f"{cidade}-{ordem}-{f_qualidade}-{f_reclamacoes}-{busca}"
            chave = f"lista-{uf}-{abs(hash(filtros))}-{st.session_state.get('_versao_lista', 0)}"
            st.session_state["_tabela_atual"] = chave
            st.session_state["_lista_atual"] = lista
            colunas = ["nome", "clientes", "qualidade", "reclamacoes"]
            if not cidade:
                colunas.insert(1, "cidade")
            st.dataframe(
                lista,
                key=chave,
                on_select=ao_escolher_operadora,
                selection_mode="single-row",
                hide_index=True,
                width="stretch",
                height=320,
                column_order=colunas,
                column_config={
                    "nome": st.column_config.TextColumn("Operadora", width="medium"),
                    "cidade": st.column_config.TextColumn("Cidade", width="small"),
                    "clientes": st.column_config.NumberColumn("Clientes", format="localized", width="small"),
                    "qualidade": st.column_config.TextColumn("Qualidade", width="small",
                                                             help="Nota IDSS da ANS em palavras"),
                    "reclamacoes": st.column_config.TextColumn("Reclamações", width="small",
                                                               help="IGR da ANS comparado à média das operadoras parecidas"),
                },
            )  # fmt: skip
            if lista.empty:
                st.info(
                    "Nenhuma operadora com esses filtros. Tente tirar algum filtro.", icon=":material/filter_alt_off:"
                )
            st.caption("Clique em uma operadora para ver os detalhes")

if reg := st.session_state.pop("_abrir", None):
    abrir_ficha(reg)

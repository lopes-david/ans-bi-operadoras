"""Planos de saúde no Brasil: escolha um estado no mapa e veja as operadoras.

Rodar: `make app` (ou `uv run --group app streamlit run app/streamlit_app.py`).
"""

from functools import partial

import pandas as pd
import streamlit as st

from classificacao import (
    QUALIDADE,
    RECLAMACOES,
    SEM_INDICE,
    SEM_NOTA,
    SEMAFORO,
    grupo_reclamacoes,
    qualidade,
    reclamacoes,
    rotulo_filtro_qualidade,
    rotulo_filtro_reclamacoes,
)
from componentes.mapa import ROXO, mapa_brasil
from data import (
    UF_NOMES,
    cidades_do_estado,
    estados_internacoes,
    fmt_compact,
    fmt_dec,
    fmt_int,
    fmt_mes,
    get_db,
    mercado_por_estado,
    operadoras_do_estado,
    sedes_por_estado,
)
from ficha_estado import abrir_ficha_estado
from ficha_operadora import abrir_ficha
from panorama_estado import painel_panorama

st.set_page_config(page_title="ANS BI · Planos de saúde", page_icon="🩺", layout="wide")


def preparar_lista(ops: pd.DataFrame, filtro_qualidade: list, filtro_reclamacoes: list, busca: str):
    """Aplica a leitura em palavras e os filtros; a ordenação fica no cabeçalho da tabela.

    A lista já vem das maiores para as menores, que é o que a maioria quer ver primeiro.
    """
    df = ops.copy()
    leitura_q = [qualidade(v) or (SEM_NOTA, None) for v in df["idss"]]
    leitura_r = [reclamacoes(i, m) or (SEM_INDICE, None) for i, m in zip(df["igr"], df["mediana_igr"], strict=True)]
    df["_qualidade"] = [t for t, _ in leitura_q]
    df["_reclamacoes"] = [t for t, _ in leitura_r]
    # na lista só a bolinha (a legenda fica abaixo da tabela; as palavras aparecem nos filtros e na ficha)
    df["qualidade"] = [SEMAFORO[c] for _, c in leitura_q]
    df["reclamacoes"] = [SEMAFORO[c] for _, c in leitura_r]
    if filtro_qualidade:
        df = df[df["_qualidade"].isin(filtro_qualidade)]
    if filtro_reclamacoes:
        df = df[df["_reclamacoes"].map(grupo_reclamacoes).isin(filtro_reclamacoes)]
    if busca:
        df = df[df["nome"].str.contains(busca, case=False, na=False, regex=False)]
    return df.sort_values("clientes", ascending=False, na_position="last").reset_index(drop=True)


# o painel lateral entra deslizando sempre que um estado novo é escolhido
st.html(
    """<style>
    /* tela inicial cabe inteira na janela: sem rolagem da página */
    .block-container { padding-top: 1rem !important; padding-bottom: 0 !important; }
    [data-testid="stHeader"] { background: transparent; }
    h1 { font-size: 1.9rem !important; padding: 0.25rem 0 0 !important; }
    .stMainBlockContainer h1 { font-size: 1.9rem; padding: 0; margin-bottom: -.4rem; }
    [class*="st-key-painel-"], [class*="st-key-panorama-"] { max-height: calc(100vh - 158px); overflow: hidden; }
    /* a lista encolhe com a janela: assim o painel inteiro não precisa de barra de rolagem */
    [class*="st-key-painel-"], [class*="st-key-panorama-"] { gap: .4rem; }
    [class*="st-key-painel-"] h3, [class*="st-key-panorama-"] h3 { font-size: 1.45rem; padding: 0; }
    /* quadros do panorama: mesma altura e mesmo espaçamento em todas as abas */
    [class*="st-key-panorama-"] [data-testid="stHorizontalBlock"] { align-items: stretch !important; }
    [class*="st-key-panorama-"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"] { height: 100%; }
    [class*="st-key-panorama-"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
      > [data-testid="stLayoutWrapper"]:only-child,
    [class*="st-key-panorama-"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
      > [data-testid="stLayoutWrapper"]:only-child > [class*="st-key-quadro-"] { height: 100%; }
    /* mesma altura em todos os quadros e em todas as abas do panorama */
    [class*="st-key-panorama-"] [class*="st-key-quadro-"] { height: 100%; min-height: 312px; }
    /* na tela do país, cada informação tem seu próprio quadro pequeno */
    [class*="st-key-quadro-pais-"] { min-height: 0 !important; }
    [class*="st-key-quadro-pais-"] [data-testid="stMetricValue"] { font-size: 1.2rem; }
    [class*="st-key-panorama-"] [data-testid="stVerticalBlockBorderWrapper"] { padding: 0.7rem 0.9rem; }
    [class*="st-key-panorama-"] [data-testid="stMetricValue"] { font-size: 1.35rem; }
    /* tela sem estado escolhido: mais respiro entre o texto e os números */
    .st-key-painel-brasil, .st-key-panorama-brasil { gap: 1rem; padding-bottom: .5rem; }
    [class*="st-key-lista-"] { flex: 1 1 auto !important; height: auto !important; min-height: 96px !important; }
    [class*="st-key-lista-"] > div, [class*="st-key-lista-"] .stDataFrame { height: 100% !important; }
    @media (max-height: 640px) { [class*="st-key-lista-"] { min-height: 84px !important; } }
    [class*="st-key-painel-"], [class*="st-key-panorama-"] { animation: entrar .45s cubic-bezier(.2,.9,.25,1); }
    @keyframes entrar { from { transform: translateX(24px); } }
    /* ficha da operadora: janela quase do tamanho da tela e compacta, sem rolagem */
    div:has(> section[role="dialog"] .st-key-ficha) { width: min(96vw, 1600px) !important; max-width: none !important; }
    section[role="dialog"]:has(.st-key-ficha) { width: 100% !important; max-width: none !important; box-sizing: border-box; }
    section[role="dialog"]:has(.st-key-ficha) [data-testid="stMetricValue"] { font-size: 1.45rem; }
    /* mesma altura da janela em todas as abas */
    section[role="dialog"]:has(.st-key-ficha) { min-height: min(580px, calc(100vh - 70px)); }
    /* quadros da mesma linha com a mesma altura */
    .st-key-ficha [data-testid="stHorizontalBlock"] { align-items: stretch !important; }
    .st-key-ficha [data-testid="stColumn"] > [data-testid="stVerticalBlock"] { height: 100%; }
    .st-key-ficha [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:only-child,
    .st-key-ficha [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:only-child
      > [class*="st-key-quadro-"] { height: 100%; }
    .st-key-ficha [class*="st-key-quadro-resumo-baixo-"] { min-height: 225px; }
    /* sem barra de ferramentas sobre os gráficos da ficha */
    .st-key-ficha [data-testid="stElementToolbar"] { display: none !important; }
    .ranking { list-style: none; margin: 0 !important; padding: 0 !important; }
    .ranking li { display: flex; align-items: center; gap: .6rem; padding: .1rem 0; font-size: .9rem; line-height: 1.35; margin: 0 !important;
                  border-bottom: 1px solid rgba(128,128,128,.15); }
    .ranking li:last-child { border-bottom: none; }
    .ranking .pos { flex: none; width: 1.2rem; height: 1.2rem; border-radius: 50%; font-size: .7rem;
                    display: grid; place-items: center; background: rgba(128,128,128,.18); }
    .ranking li:first-child .pos { background: rgba(255,108,108,.25); }
    .ranking .tema { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ranking .qtd { flex: none; opacity: .65; font-size: .8rem; }
    .ranking .qtd b { opacity: 1; font-weight: 600; }
    section[role="dialog"]:has(.st-key-ficha) [data-testid="stVerticalBlock"] { gap: 0.55rem; }
    section[role="dialog"]:has(.st-key-ficha) [data-testid="stVerticalBlockBorderWrapper"] { padding: 0.7rem 0.9rem; }
    section[role="dialog"]:has(.st-key-ficha) ul { margin-bottom: 0; }
    @media (prefers-reduced-motion: reduce) { [class*="st-key-painel-"], [class*="st-key-panorama-"] { animation: none; } }
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


def ao_clicar_no_mapa(key: str = "mapa"):
    evento = st.session_state[key]
    clique = evento.get("clique") if hasattr(evento, "get") else getattr(evento, "clique", None)
    if clique is None:
        return
    # no mapa do panorama o estado só abre a janela: fechar a janela desmarca o estado
    if key == "mapa-estado":
        escolhido = clique.get("uf")
        if escolhido:
            st.session_state["_ficha_estado"] = escolhido
        else:
            st.session_state.pop("_ficha_estado", None)
        return
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
st.title("Planos de saúde no Brasil", anchor=False)
st.caption(f"Clique em um estado no mapa · dados da ANS de {fmt_mes(db.ref)}")

aba_operadoras, aba_estado = st.tabs(["Operadoras", "Panorama do estado"])

with aba_operadoras:
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
        mapa_brasil(valores, uf, key="mapa", on_clique=partial(ao_clicar_no_mapa, "mapa"),
                    legenda=("menos operadoras", "mais operadoras"))  # fmt: skip

    with col_lado:
        if not uf:
            with st.container(border=True, key="painel-brasil"):
                st.subheader("Escolha um estado", anchor=False)
                st.caption("Clique no mapa para ver as operadoras com sede no estado.")
                a, b = st.columns(2)
                a.metric("Operadoras", fmt_int(por_estado["operadoras"].sum()), "ativas com clientes",
                         delta_color="off", delta_arrow="off")  # fmt: skip
                b.metric("Clientes", fmt_compact(por_estado["clientes"].sum()), "no Brasil", delta_color="off",
                         delta_arrow="off")  # fmt: skip
        else:
            with st.container(border=True, key=f"painel-{uf}"):
                topo, fechar = st.columns([5, 1], vertical_alignment="center")
                topo.subheader(UF_NOMES[uf], anchor=False)
                fechar.button("", icon=":material/close:", on_click=limpar_estado, help="Voltar ao Brasil",
                              key="fechar", width="stretch")  # fmt: skip

                # rótulos dentro dos próprios campos: a tela não sobra altura para rótulos em cima
                c1, c3, c4, c5 = st.columns([3, 3, 3, 4])
                cidade = c1.selectbox("Cidade da sede", [None, *cidades_do_estado(uf)], key=f"cidade-{uf}",
                                      label_visibility="collapsed",
                                      format_func=lambda c: "Cidade: todas" if c is None else c)  # fmt: skip
                f_qualidade = c3.multiselect(
                    "Qualidade (IDSS)",
                    QUALIDADE,
                    key="f_qualidade",
                    placeholder="Qualidade",
                    label_visibility="collapsed",
                    format_func=rotulo_filtro_qualidade,
                    help="Nota anual da ANS. 🟢 boa · 🟡 regular · 🔴 ruim",
                )
                f_reclamacoes = c4.multiselect("Reclamações (IGR)", RECLAMACOES, key="f_reclamacoes",
                                               placeholder="Reclamações", label_visibility="collapsed",
                                               format_func=rotulo_filtro_reclamacoes,
                                               help="Reclamações na ANS para cada 100 mil clientes, comparadas com a "
                                                    "média das operadoras parecidas.")  # fmt: skip
                busca = c5.text_input("Buscar operadora", placeholder="Buscar pelo nome…", key=f"busca-{uf}",
                                      label_visibility="collapsed")  # fmt: skip
                onde = cidade or UF_NOMES[uf]

                ops = operadoras_do_estado(uf, cidade)
                lista = preparar_lista(ops, f_qualidade, f_reclamacoes, busca)
                st.caption(f"**{fmt_int(len(lista))}** operadoras com sede em {onde} · "
                            f"**{fmt_compact(lista['clientes'].sum())}** clientes no Brasil")  # fmt: skip

                filtros = f"{cidade}-{f_qualidade}-{f_reclamacoes}-{busca}"
                chave = f"lista-{uf}-{abs(hash(filtros))}-{st.session_state.get('_versao_lista', 0)}"
                st.session_state["_tabela_atual"] = chave
                st.session_state["_lista_atual"] = lista
                colunas = ["nome", "registro_ans", "clientes", "qualidade", "reclamacoes"]
                if not cidade:
                    colunas.insert(2, "cidade")
                st.dataframe(
                    lista,
                    key=chave,
                    on_select=ao_escolher_operadora,
                    selection_mode="single-row",
                    hide_index=True,
                    width="stretch",
                    height=320,  # base: o CSS acima ajusta à altura da janela
                    column_order=colunas,
                    column_config={
                        "nome": st.column_config.TextColumn("Operadora", width=150),
                        "registro_ans": st.column_config.TextColumn("Código", width=68,
                                                                    help="Registro da operadora na ANS: diferencia unidades de mesmo nome (as Unimeds, por exemplo)"),
                        "cidade": st.column_config.TextColumn("Cidade", width=82),
                        "clientes": st.column_config.NumberColumn("Clientes", format="localized", width=76),
                        "qualidade": st.column_config.TextColumn("Qualid.", width=58,
                                                                 help="Nota anual de qualidade da ANS (IDSS): 🟢 boa (6 a 10) · 🟡 regular (4 a 6) · 🔴 ruim (abaixo de 4)"),
                        "reclamacoes": st.column_config.TextColumn("Reclam.", width=58,
                                                                   help="Reclamações na ANS por cliente (IGR), comparadas com operadoras parecidas: 🟢 poucas · 🟡 acima da média · 🔴 muitas"),
                    },
                )  # fmt: skip
                if lista.empty:
                    st.info(
                        "Nenhuma operadora com esses filtros. Tente tirar algum filtro.",
                        icon=":material/filter_alt_off:",
                    )
                st.caption("🟢 bom · 🟡 atenção · 🔴 ruim · ⚪ sem dados")

with aba_estado:
    col_mapa_estado, col_panorama = st.columns([1, 1], gap="large")
    with col_mapa_estado:
        internacoes = estados_internacoes()
        calor = internacoes.set_index("uf") if not internacoes.empty else mercado_por_estado().set_index("uf")
        coluna = "internacoes_100mil" if not internacoes.empty else "clientes"
        cores_estado = {
            sigla: (
                {
                    "nome": nome,
                    "valor": float(calor.at[sigla, coluna]),
                    "texto": (f"{fmt_int(calor.at[sigla, 'internacoes_100mil'])} internações por 100 mil clientes · "
                              f"{fmt_dec(calor.at[sigla, 'dias_por_internacao'], 1)} dias em média"
                              if coluna == "internacoes_100mil" else f"{fmt_compact(calor.at[sigla, 'clientes'])} "
                              "pessoas com plano"),
                }
                if sigla in calor.index
                else {"nome": nome, "valor": 0, "texto": "sem dados de internação"}
            )
            for sigla, nome in UF_NOMES.items()
        }  # fmt: skip
        mapa_brasil(cores_estado, st.session_state.get("_ficha_estado"), key="mapa-estado",
                    on_clique=partial(ao_clicar_no_mapa, "mapa-estado"),
                    paleta=ROXO, legenda=("menos internações", "mais internações"))  # fmt: skip
    with col_panorama:
        painel_panorama(uf)


# a ficha fica aberta entre execuções (os widgets dentro dela reexecutam o script)
if escolhida := st.session_state.pop("_abrir", None):
    st.session_state["_ficha"] = escolhida
if reg := st.session_state.get("_ficha"):
    abrir_ficha(reg)
if estado := st.session_state.get("_ficha_estado"):
    abrir_ficha_estado(estado)

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
    SEMAFORO,
    grupo_reclamacoes,
    qualidade,
    reclamacoes,
    rotulo_filtro_qualidade,
    rotulo_filtro_reclamacoes,
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


# critério -> (coluna, faixa em palavras, crescente); a faixa agrupa antes do valor exato
CRITERIOS = {
    "clientes": ("clientes", None, False),
    "melhor_qualidade": ("idss", "_faixa_q", False),
    "pior_qualidade": ("idss", "_faixa_q", True),
    "menos_reclamacoes": ("_proporcao", "_faixa_r", True),
    "mais_reclamacoes": ("_proporcao", "_faixa_r", False),
}
FAIXA_RECLAMACOES = [*RECLAMACOES_CURTO, SEM_INDICE]


def criterios_validos(ordem: list[str]) -> list[str]:
    """Mantém a ordem escolhida e descarta o oposto de algo já escolhido (ex.: melhor e pior qualidade)."""
    usados, validos = set(), []
    for criterio in ordem or ["clientes"]:
        coluna = CRITERIOS[criterio][0]
        if coluna not in usados:
            usados.add(coluna)
            validos.append(criterio)
    return validos


def preparar_lista(ops: pd.DataFrame, ordem: list[str], filtro_qualidade: list, filtro_reclamacoes: list, busca: str):
    """Aplica a leitura em palavras, os filtros e a ordenação (vários critérios, na ordem escolhida)."""
    df = ops.copy()
    leitura_q = [qualidade(v) or (SEM_NOTA, None) for v in df["idss"]]
    leitura_r = [reclamacoes(i, m) or (SEM_INDICE, None) for i, m in zip(df["igr"], df["mediana_igr"], strict=True)]
    df["_qualidade"] = [t for t, _ in leitura_q]
    df["_reclamacoes"] = [t for t, _ in leitura_r]
    # na lista só a bolinha (a legenda fica abaixo da tabela; as palavras aparecem nos filtros e na ficha)
    df["qualidade"] = [SEMAFORO[c] for _, c in leitura_q]
    df["reclamacoes"] = [SEMAFORO[c] for _, c in leitura_r]
    df["_proporcao"] = df["igr"] / df["mediana_igr"]  # compara operadoras de coberturas diferentes
    # posição da faixa (0 = melhor); sem nota/sem dados vão sempre para o fim
    df["_faixa_q"] = df["_qualidade"].map({t: i for i, t in enumerate([*QUALIDADE, SEM_NOTA])})
    df["_faixa_r"] = df["_reclamacoes"].map({t: i for i, t in enumerate(FAIXA_RECLAMACOES)})
    if filtro_qualidade:
        df = df[df["_qualidade"].isin(filtro_qualidade)]
    if filtro_reclamacoes:
        df = df[df["_reclamacoes"].map(grupo_reclamacoes).isin(filtro_reclamacoes)]
    if busca:
        df = df[df["nome"].str.contains(busca, case=False, na=False, regex=False)]
    criterios = [CRITERIOS[c] for c in criterios_validos(ordem)]
    # com mais de um critério, os primeiros agrupam por faixa (muito boa, boa...) e o último decide pelo valor exato
    colunas, crescentes = [], []
    for coluna, faixa, crescente in criterios[:-1]:
        if not faixa:
            colunas.append(coluna)
            crescentes.append(crescente)
            continue
        sem_dados = len(QUALIDADE) if faixa == "_faixa_q" else len(FAIXA_RECLAMACOES) - 1
        melhor_primeiro = crescente if faixa == "_faixa_r" else not crescente
        # "pior primeiro" inverte as faixas, mas quem não tem dados continua no fim
        df[f"{faixa}_ord"] = df[faixa] if melhor_primeiro else df[faixa].where(df[faixa] == sem_dados, -df[faixa])
        colunas.append(f"{faixa}_ord")
        crescentes.append(True)
    coluna, _, crescente = criterios[-1]
    colunas.append(coluna)
    crescentes.append(crescente)
    if "clientes" not in colunas:
        colunas.append("clientes")  # desempate final: a maior
        crescentes.append(False)
    return df.sort_values(colunas, ascending=crescentes, na_position="last").reset_index(drop=True)


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

            c1, c3, c4 = st.columns(3)
            cidade = c1.selectbox("Cidade da sede", [None, *cidades_do_estado(uf)], key=f"cidade-{uf}",
                                  format_func=lambda c: "Todas" if c is None else c)  # fmt: skip
            f_qualidade = c3.multiselect(
                "Qualidade (IDSS)",
                QUALIDADE,
                key="f_qualidade",
                placeholder="Todas",
                format_func=rotulo_filtro_qualidade,
                help="Nota anual da ANS. 🟢 boa · 🟡 regular · 🔴 ruim",
            )
            f_reclamacoes = c4.multiselect("Reclamações (IGR)", RECLAMACOES, key="f_reclamacoes", placeholder="Todas",
                                           format_func=rotulo_filtro_reclamacoes,
                                           help="Reclamações na ANS para cada 100 mil clientes, comparadas com a "
                                                "média das operadoras parecidas.")  # fmt: skip
            ordem = st.multiselect("Ordenar por (escolha um ou mais, na ordem de importância)", list(ORDENS),
                                   format_func=ORDENS.get, key="ordem", placeholder="Mais clientes",
                                   max_selections=3,
                                   help="O primeiro critério manda. Ex.: Melhor qualidade + Menos reclamações "
                                        "mostra primeiro as de nota boa e, entre elas, as que menos recebem "
                                        "reclamações.")  # fmt: skip
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
                                                             help="Nota anual de qualidade da ANS (IDSS): 🟢 boa (6 a 10) · 🟡 regular (4 a 6) · 🔴 ruim (abaixo de 4)"),
                    "reclamacoes": st.column_config.TextColumn("Reclamações", width="small",
                                                               help="Reclamações na ANS por cliente (IGR), comparadas com operadoras parecidas: 🟢 poucas · 🟡 acima da média · 🔴 muitas"),
                },
            )  # fmt: skip
            if lista.empty:
                st.info(
                    "Nenhuma operadora com esses filtros. Tente tirar algum filtro.", icon=":material/filter_alt_off:"
                )
            st.caption("🟢 bom · 🟡 atenção · 🔴 ruim · ⚪ sem dados — clique em uma operadora para ver os detalhes")

if reg := st.session_state.pop("_abrir", None):
    abrir_ficha(reg)

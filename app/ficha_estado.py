"""Ficha do estado: a mesma janela da ficha da operadora, com os dados que só existem somados.

Tudo aqui é do estado aberto. A média do país aparece só como referência escrita ("9% acima do país"),
nunca como um gráfico cheio de outros estados.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts
import ui
from data import (
    UF_NOMES,
    ano_das_internacoes,
    comparativo_idade,
    estados_internacoes,
    fmt_compact,
    fmt_dec,
    fmt_int,
    fmt_mes,
    idade_media_por_estado,
    internacoes_por_idade,
    panorama_estado,
    perfil_das_internacoes,
    series_do_estado,
    tempo_por_tipo,
)

ASSUNTOS_NA_FICHA = 4


def _posicao(estados: pd.DataFrame, uf: str, coluna: str) -> int:
    ordenado = estados.sort_values(coluna, ascending=False).reset_index(drop=True)
    return int(ordenado.index[ordenado["uf"] == uf][0]) + 1


def _comparado(valor, media, invertido: bool = False) -> tuple[str, str]:
    """Quanto o estado está acima ou abaixo da média do país, já em palavras e cor."""
    if not media:
        return "sem comparação", "gray"
    dif = 100 * (valor - media) / media
    if abs(dif) < 3:
        return "na média do país", "gray"
    acima = dif > 0
    cor = ("red" if acima else "green") if not invertido else ("green" if acima else "red")
    return f"{fmt_dec(abs(dif), 0)}% {'acima' if acima else 'abaixo'} do país", cor


def _aba_internacoes(uf: str, estados: pd.DataFrame, idades: pd.DataFrame, series: dict) -> None:
    linha = estados[estados["uf"] == uf].iloc[0]
    media = 100000 * estados["internacoes"].sum() / estados["clientes"].sum()
    media_dias = estados["dias"].sum() / estados["internacoes"].sum()
    perfil = perfil_das_internacoes(uf)
    esquerda, meio, direita = st.columns([5, 5, 4])

    with esquerda, ui.quadro("Interna mais ou menos que o país?", chave="uf-quanto"):
        leitura, cor = _comparado(linha.internacoes_100mil, media)
        a, b = st.columns(2)
        a.metric("Internações", fmt_compact(linha.internacoes_100mil), leitura, delta_color=cor, delta_arrow="off",
                 help="Internações por 100 mil pessoas com plano no estado.")  # fmt: skip
        b.metric("Posição", f"{_posicao(estados, uf, 'internacoes_100mil')}º", f"entre {len(estados)} estados",
                 delta_color="off", delta_arrow="off")  # fmt: skip
        serie = series["internacoes"]
        if len(serie) >= 4:
            st.altair_chart(charts.linha(serie, fmt_int, altura=175, trimestral=True), width="stretch")
            st.caption("Internações por trimestre no estado.")

    with meio, ui.quadro("Quanto tempo dura a internação?", chave="uf-tempo"):
        leitura, cor = _comparado(linha.dias_por_internacao, media_dias)
        a, b = st.columns(2)
        a.metric("Dias internado", fmt_dec(linha.dias_por_internacao, 1), leitura, delta_color=cor,
                 delta_arrow="off", help=f"Média do país: {fmt_dec(media_dias, 1)} dias.")  # fmt: skip
        b.metric("Em UTI", f"{fmt_dec(linha.pct_uti, 0)}%", "do tempo internado", delta_color="off",
                 delta_arrow="off")  # fmt: skip
        tipos = tempo_por_tipo(uf)
        if not tipos.empty:
            st.altair_chart(
                charts.colunas(tipos, "tipo", lambda v: fmt_dec(v, 1), rotulo_x=str, altura=175, valores=True),
                width="stretch",
            )
            mais_longa = tipos.loc[tipos["valor"].idxmax()]
            st.caption(f"Dias por internação, por tipo. A mais longa é a **{mais_longa.tipo.lower()}** "
                       f"({fmt_dec(mais_longa.valor, 1)} dias).")  # fmt: skip

    with direita, ui.quadro("Por que as pessoas internam?", chave="uf-motivo"):
        if not perfil:
            st.caption("A ANS não publicou internações para este estado.")
            return
        urgencia = 100 * perfil["urgencia"] / perfil["total"]
        st.metric("Urgência", f"{fmt_dec(urgencia, 0)}%", "não foram planejadas", delta_color="red",
                  delta_arrow="off", help="Internações de urgência ou emergência; o resto é eletivo.")  # fmt: skip
        st.html(ui.ranking(perfil["tipos"].head(4), "tipo", "internacoes", total=perfil["tipos"]["internacoes"].sum()))
        idade = idades[idades["uf"] == uf]
        if not idade.empty:
            st.caption(f"Idade média de quem interna aqui: **{fmt_dec(idade.iloc[0].idade_media, 0)} anos**.")


def _aba_idade(uf: str, idades: pd.DataFrame) -> None:
    comparado = comparativo_idade(uf)
    esquerda, direita = st.columns([7, 5])
    with esquerda, ui.quadro("A idade explica a internação?", "internações por 100 pessoas com plano",
                             chave="uf-idade"):  # fmt: skip
        if comparado.empty:
            st.caption("A ANS não publicou internações para este estado.")
        else:
            aqui = comparado[comparado["serie"] == "Aqui"].set_index("faixa")["valor"]
            brasil = comparado[comparado["serie"] == "Brasil"].set_index("faixa")["valor"]
            st.altair_chart(
                charts.colunas(aqui.reset_index(), "faixa", lambda v: fmt_dec(v, 1), rotulo_x=str, altura=210,
                               valores=True),
                width="stretch",
            )  # fmt: skip
            vezes = aqui.iloc[-1] / aqui.iloc[0] if aqui.iloc[0] else None
            diferente = (aqui - brasil).abs().idxmax()
            st.caption(f"Quem tem 70 anos ou mais interna **{fmt_dec(vezes, 1)}x** mais que quem tem 0 a 14 · "
                       f"a faixa que mais foge da média do país é **{diferente}**.")  # fmt: skip

    with direita, ui.quadro("Quem envelhece, interna", chave="uf-idosos"):
        estado = idades[idades["uf"] == uf]
        if estado.empty:
            st.caption("Sem dados de idade para este estado.")
        else:
            pct = estado.iloc[0].pct_idosos
            a, b = st.columns(2)
            a.metric("Clientes com 70+", f"{fmt_dec(pct, 0)}%", _comparado(pct, idades["pct_idosos"].mean())[0],
                     delta_color="off", delta_arrow="off")  # fmt: skip
            b.metric("Idade de quem interna", f"{fmt_dec(estado.iloc[0].idade_media, 0)}", "anos em média",
                     delta_color="off", delta_arrow="off")  # fmt: skip
            clientes = internacoes_por_idade(uf).rename(columns={"clientes": "valor"})
            if not clientes.empty:
                st.altair_chart(
                    charts.colunas(clientes, "faixa", fmt_compact, rotulo_x=str, altura=155), width="stretch"
                )
                st.caption("Pessoas com plano em cada faixa de idade.")


def _aba_reclamacoes(uf: str, estados: pd.DataFrame, dados: dict, series: dict) -> None:
    from ficha_operadora import ASSUNTOS  # os mesmos rótulos em linguagem simples da ficha da operadora

    linha = estados[estados["uf"] == uf].iloc[0]
    esquerda, direita = st.columns([6, 6])
    with esquerda, ui.quadro("Quanto se reclama aqui?", chave="uf-relacao"):
        relacao = estados["internacoes_100mil"].corr(estados["reclamacoes_100mil"])
        media = 100000 * estados["reclamacoes"].sum() / estados["clientes"].sum()
        leitura, cor = _comparado(linha.reclamacoes_100mil, media)
        a, b = st.columns(2)
        a.metric("Reclamações", fmt_int(linha.reclamacoes_100mil), leitura, delta_color=cor, delta_arrow="off",
                 help="Reclamações na ANS por 100 mil pessoas com plano.")  # fmt: skip
        b.metric("Internações", fmt_compact(linha.internacoes_100mil), "por 100 mil", delta_color="off",
                 delta_arrow="off")  # fmt: skip
        serie = series["reclamacoes"]
        if len(serie) >= 4:
            st.altair_chart(charts.linha(serie, fmt_int, altura=175, trimestral=True), width="stretch")
        st.caption(f"Reclamações por trimestre no estado · no país, internar mais não significa reclamar mais "
                   f"(relação de {fmt_dec(abs(relacao), 2)}).")  # fmt: skip

    with direita, ui.quadro("Do que se reclama aqui", "últimos 12 meses", chave="uf-assuntos"):
        assuntos = dados["assuntos"]
        natureza = dados["natureza"]
        total = natureza["demandas"].sum() if not natureza.empty else 0
        if assuntos.empty or not total:
            st.caption("Nenhuma reclamação registrada na ANS no último ano.")
            return
        por_tipo = dict(zip(natureza["natureza"], natureza["demandas"], strict=True))
        a, b = st.columns(2)
        a.metric("Reclamações", fmt_compact(total), "feitas à ANS", delta_color="off", delta_arrow="off")
        b.metric("Sobre atendimento", f"{fmt_dec(100 * por_tipo.get('Assistencial', 0) / total, 0)}%",
                 "exame, consulta, cirurgia", delta_color="off", delta_arrow="off")  # fmt: skip
        por_tema = (
            assuntos.assign(tema=assuntos["assunto"].map(lambda a: ASSUNTOS.get(a, a)))
            .groupby("tema", as_index=False)["reclamacoes"]
            .sum()
            .sort_values("reclamacoes", ascending=False)
            .head(ASSUNTOS_NA_FICHA)
        )
        st.html(ui.ranking(por_tema, "tema", "reclamacoes", total=assuntos["reclamacoes"].sum()))


PERIODOS = {"12 meses": 1, "3 anos": 3, "Desde 2021": None}
CONTRATACAO_CURTO = {
    "Coletivo empresarial": "Pelo trabalho",
    "Individual ou familiar": "Individual",
    "Coletivo por adesão": "Por associação",
    "Outros / não identificado": "Outros",
}


def _crescimento(serie: pd.DataFrame, anos: int | None) -> tuple[pd.DataFrame, float | None, str]:
    """Recorta a série no período escolhido e calcula quanto o mercado cresceu nele."""
    if serie.empty:
        return serie, None, ""
    fim = pd.Timestamp(serie.iloc[-1].competencia)
    trecho = serie if anos is None else serie[pd.to_datetime(serie["competencia"]) >= fim - pd.DateOffset(years=anos)]
    if len(trecho) < 2 or not trecho.iloc[0].valor:
        return trecho, None, ""
    inicio, atual = trecho.iloc[0], trecho.iloc[-1]
    pct = 100 * (atual.valor - inicio.valor) / inicio.valor
    return trecho, pct, f"desde {fmt_mes(inicio.ate)}"


def _aba_mercado(uf: str, dados: dict, series: dict) -> None:
    esquerda, direita = st.columns([7, 5])
    with esquerda, ui.quadro("Como o mercado cresceu", chave="uf-mercado"):
        escolha = st.pills("Período", list(PERIODOS), default="12 meses", key=f"periodo-{uf}",
                           label_visibility="collapsed") or "12 meses"  # fmt: skip
        trecho, pct, desde = _crescimento(dados["serie_tri"], PERIODOS[escolha])
        a, b = st.columns(2)
        a.metric("Pessoas com plano", fmt_compact(dados["clientes"]), f"em {fmt_int(dados['municipios'])} municípios",
                 delta_color="off", delta_arrow="off")  # fmt: skip
        if pct is None:
            b.metric("No período", "—", "sem histórico", delta_color="gray", delta_arrow="off")
        else:
            cor = "green" if pct > 0.5 else "red" if pct < -0.5 else "gray"
            sinal = "+" if pct > 0 else "−" if pct < 0 else ""
            b.metric("No período", f"{sinal}{fmt_dec(abs(pct), 1)}%", desde, delta_color=cor, delta_arrow="off",
                     help="Variação do total de pessoas com plano no estado.")  # fmt: skip
        if len(trecho) >= 3:
            st.altair_chart(charts.linha(trecho, fmt_int, altura=150, trimestral=True), width="stretch")

    with direita, ui.quadro("Ano a ano", chave="uf-anos"):
        ui.variacao_por_ano(series["clientes_ano"], subir_e_bom=True,
                            titulo="Clientes a mais ou a menos que no ano anterior:")  # fmt: skip
        contratacao = series["contratacao"]
        total = contratacao["clientes"].sum() if not contratacao.empty else 0
        if total:
            st.caption("Como as pessoas contrataram:")
            fatias = [linha for linha in contratacao.itertuples() if linha.clientes / total >= 0.01]
            for col, linha in zip(st.columns(len(fatias)), fatias, strict=True):
                curto = CONTRATACAO_CURTO.get(linha.contratacao, linha.contratacao)
                col.metric(curto, f"{fmt_dec(100 * linha.clientes / total, 0)}%",
                           help=f"{linha.contratacao}: {fmt_int(linha.clientes)} clientes.")  # fmt: skip


def _conteudo_ficha_estado(uf: str) -> None:
    estados = estados_internacoes()
    idades = idade_media_por_estado()
    dados = panorama_estado(uf)
    series = series_do_estado(uf)
    with st.container(key="ficha"):
        st.caption(f"**{fmt_compact(dados['clientes'])}** pessoas com plano · internações de "
                   f"{ano_das_internacoes()} · reclamações dos últimos 12 meses")  # fmt: skip
        tem_internacoes = not estados.empty and uf in set(estados["uf"])
        internacoes, idade, reclamacoes, mercado = st.tabs(["Internações", "Idade", "Reclamações", "Mercado"])
        with internacoes:
            if tem_internacoes:
                _aba_internacoes(uf, estados, idades, series)
            else:
                st.caption("A ANS não publicou internações para este estado.")
        with idade:
            if tem_internacoes:
                _aba_idade(uf, idades)
            else:
                st.caption("A ANS não publicou internações para este estado.")
        with reclamacoes:
            if tem_internacoes:
                _aba_reclamacoes(uf, estados, dados, series)
            else:
                st.caption("A ANS não publicou internações para este estado.")
        with mercado:
            _aba_mercado(uf, dados, series)


def fechar_ficha_estado() -> None:
    st.session_state.pop("_ficha_estado", None)


def abrir_ficha_estado(uf: str) -> None:
    """Abre a janela do estado, no mesmo formato da ficha da operadora."""
    st.dialog(UF_NOMES[uf], width="large", on_dismiss=fechar_ficha_estado)(_conteudo_ficha_estado)(uf)

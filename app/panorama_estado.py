"""Panorama do estado: o que só faz sentido somando todas as operadoras.

O fio condutor é a internação (base TISS, que a ANS publica sem identificar a operadora), cruzada com
quem tem plano naquele estado: quanto se interna, por quanto tempo, em que idade e se isso tem alguma
relação com as reclamações.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from data import (
    UF_NOMES,
    ano_das_internacoes,
    estados_internacoes,
    fmt_compact,
    fmt_dec,
    idade_media_por_estado,
    perfil_das_internacoes,
)

ITENS_NO_RANKING = 4


def _campeao(estados: pd.DataFrame, coluna: str, maior: bool = True) -> pd.Series:
    return estados.loc[estados[coluna].idxmax() if maior else estados[coluna].idxmin()]


def _numero(coluna, titulo: str, valor: str, detalhe: str, cor: str, chave: str, ajuda: str | None = None) -> None:
    """Um quadro por informação: título, número e leitura — sem misturar assuntos no mesmo quadro."""
    with coluna, ui.quadro(titulo, chave=f"pais-{chave}"):
        st.metric(titulo, valor, detalhe, delta_color=cor, delta_arrow="off", help=ajuda,
                  label_visibility="collapsed")  # fmt: skip


def _destaques_do_pais() -> None:
    """Tela de entrada: os recordes do país, um por quadro."""
    estados = estados_internacoes()
    with st.container(border=True, key="panorama-brasil"):
        st.subheader("Internações no Brasil", anchor=False)
        st.caption(f"Em {ano_das_internacoes()} · clique em um estado no mapa para ver o dele")
        if estados.empty:
            st.caption("A ANS não publicou internações.")
            return
        perfil = perfil_das_internacoes()
        idades = idade_media_por_estado()
        mais = _campeao(estados, "internacoes_100mil")
        menos = _campeao(estados, "internacoes_100mil", maior=False)
        demorado = _campeao(estados, "dias_por_internacao")
        grandes = estados.nlargest(10, "clientes")
        economico = grandes.loc[grandes["internacoes_100mil"].idxmin()]
        idoso = idades.loc[idades["pct_idosos"].idxmax()] if not idades.empty else None

        a, b = st.columns(2)
        _numero(a, "Interna mais", UF_NOMES[mais.uf], f"{fmt_compact(mais.internacoes_100mil)} por 100 mil",
                "red", "mais", "Internações por 100 mil pessoas com plano.")  # fmt: skip
        _numero(b, "Interna menos", UF_NOMES[menos.uf], f"{fmt_compact(menos.internacoes_100mil)} por 100 mil",
                "green", "menos", "Internações por 100 mil pessoas com plano.")  # fmt: skip

        c, d = st.columns(2)
        _numero(c, "Mais tempo internado", UF_NOMES[demorado.uf],
                f"{fmt_dec(demorado.dias_por_internacao, 1)} dias", "yellow", "tempo",
                "Média de dias de cada internação.")  # fmt: skip
        _numero(d, "Grande e interna pouco", UF_NOMES[economico.uf],
                f"{fmt_compact(economico.internacoes_100mil)} por 100 mil", "green", "grande",
                "Entre os 10 estados com mais pessoas com plano, o de menor taxa.")  # fmt: skip

        e, f = st.columns(2)
        _numero(e, "Idade de quem interna", f"{fmt_dec(perfil['idade_media'], 0)} anos", "média do país", "off",
                "idade", "Estimada pelo ponto médio das faixas publicadas pela ANS.")  # fmt: skip
        _numero(f, "Urgência", f"{fmt_dec(100 * perfil['urgencia'] / perfil['total'], 0)}%", "não planejadas",
                "red", "urgencia", "Internações de urgência ou emergência.")  # fmt: skip

        if idoso is not None:
            g, h = st.columns(2)
            _numero(g, "Mais clientes com 70+", UF_NOMES[idoso.uf], f"{fmt_dec(idoso.pct_idosos, 0)}% dos clientes",
                    "yellow", "idosos")  # fmt: skip
            tipo = perfil["tipos"].iloc[0]
            _numero(h, "Tipo mais comum", tipo.tipo,
                    f"{fmt_dec(100 * tipo.internacoes / perfil['tipos']['internacoes'].sum(), 0)}% das internações",
                    "off", "tipo")  # fmt: skip


def painel_panorama(uf: str | None) -> None:
    """Conteúdo da aba 'Panorama do estado': os recordes do país; o estado abre em janela."""
    _destaques_do_pais()

"""Peças visuais usadas na ficha da operadora e no panorama do estado."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from data import fmt_dec, fmt_int


def quadro(titulo: str, subtitulo: str | None = None, chave: str | None = None):
    """Seção com borda e título: cada tipo de informação no seu quadro."""
    caixa = st.container(border=True, key=f"quadro-{chave or abs(hash(titulo))}")
    caixa.markdown(f"**{titulo}**" + (f" · {subtitulo}" if subtitulo else ""))
    return caixa


def ranking(df: pd.DataFrame, rotulo: str, valor: str, total=None) -> str:
    """Lista numerada: posição, nome e, à direita, quantidade (e a fatia do total, quando faz sentido)."""
    linhas = ""
    for i, linha in enumerate(df.itertuples(), 1):
        n = getattr(linha, valor)
        fatia = f" · {fmt_dec(100 * n / total, 0)}%" if total else ""
        linhas += (
            f'<li><span class="pos">{i}</span><span class="tema">{escape(str(getattr(linha, rotulo)))}</span>'
            f'<span class="qtd"><b>{fmt_int(n)}</b>{fatia}</span></li>'
        )
    return f"<ol class='ranking'>{linhas}</ol>"


ANOS_NA_VARIACAO = 5


def variacao_por_ano(serie: pd.DataFrame, subir_e_bom: bool, titulo: str, ajustes: dict | None = None) -> None:
    """Variação de cada ano contra o anterior, lado a lado ("2023 +42%").

    O rótulo vem antes dos números porque sem ele "+26%" é lido como se fosse o valor do ano.
    `ajustes` desconta da variação o que não é real (ex.: transferência de carteira) por ano.
    """
    itens = []
    for antes, depois in zip(serie.itertuples(), serie.iloc[1:].itertuples(), strict=False):
        if not antes.valor:
            continue
        pct = 100 * (depois.valor - (ajustes or {}).get(depois.ano, 0) - antes.valor) / antes.valor
        ano = f"{depois.ano}\\*" if pd.Timestamp(depois.ate).month < 12 else str(depois.ano)
        casas = 0 if abs(pct) >= 10 else 1
        if round(pct, casas) == 0:
            selo = ":gray-badge[estável]"
        else:
            cor = "green" if (pct > 0) == subir_e_bom else "red"
            selo = f":{cor}-badge[{'+' if pct > 0 else '−'}{fmt_dec(abs(pct), casas)}%]"
        itens.append((ano, selo))
    itens = itens[-ANOS_NA_VARIACAO:]
    if itens:
        st.caption(titulo)
        for col, (ano, selo) in zip(st.columns(len(itens), gap="xxsmall"), itens, strict=True):
            col.markdown(f"**{ano}**  \n{selo}", text_alignment="center")

"""Dois gráficos simples (linha e colunas), com rótulos em pt-BR."""

from __future__ import annotations

import altair as alt
import pandas as pd

from data import MESES, fmt_mes

COR = "#2a78d6"
TEXTO = "#6b6a66"
GRADE = "rgba(128,128,128,0.18)"

_MESES_JS = "[" + ",".join(f"'{m}'" for m in MESES) + "]"
MES = f"{_MESES_JS}[month(datum.value)] + '/' + substring(toString(year(datum.value)), 2)"
COMPACTO = (
    "abs(datum.value) >= 1e6 ? replace(format(datum.value / 1e6, '.1~f'), '.', ',') + ' mi' : "
    "abs(datum.value) >= 1e3 ? replace(format(datum.value / 1e3, '.1~f'), '.', ',') + ' mil' : "
    "replace(format(datum.value, '.2~f'), '.', ',')"
)


def _estilo(chart, altura: int):
    return (
        chart.properties(height=altura)
        .configure_view(stroke=None)
        .configure_axis(labelColor=TEXTO, gridColor=GRADE, domain=False, ticks=False, labelFontSize=12,
                        labelPadding=6, title=None)
    )  # fmt: skip


def linha(df: pd.DataFrame, formato, altura: int = 260):
    """Série mensal; df tem colunas competencia e valor. O eixo não começa no zero para mostrar a variação."""
    dados = df.assign(_mes=df["competencia"].map(fmt_mes), _valor=df["valor"].map(formato))
    base = alt.Chart(dados).encode(
        x=alt.X("competencia:T", axis=alt.Axis(labelExpr=MES, grid=False, labelAngle=0, tickCount=6)),
        y=alt.Y("valor:Q", scale=alt.Scale(zero=False), axis=alt.Axis(labelExpr=COMPACTO, tickCount=4)),
        tooltip=[alt.Tooltip("_mes:N", title="Mês"), alt.Tooltip("_valor:N", title="Total")],
    )
    traco = base.mark_line(color=COR, strokeWidth=2.5, point=alt.OverlayMarkDef(size=36, filled=True, color=COR))
    return _estilo(traco, altura)


def colunas(df: pd.DataFrame, x: str, formato, rotulo_x=fmt_mes, altura: int = 260):
    dados = df.assign(_x=df[x].map(rotulo_x), _valor=df["valor"].map(formato))
    chart = (
        alt.Chart(dados)
        .mark_bar(color=COR, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=16)
        .encode(
            x=alt.X("_x:O", sort=None, axis=alt.Axis(labelAngle=0, labelOverlap="greedy")),
            y=alt.Y("valor:Q", axis=alt.Axis(labelExpr=COMPACTO, tickCount=4)),
            tooltip=[alt.Tooltip("_x:N", title="Período"), alt.Tooltip("_valor:N", title="Total")],
        )
    )
    return _estilo(chart, altura)

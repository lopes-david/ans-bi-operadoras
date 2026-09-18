"""Dois gráficos simples (linha e colunas), com rótulos em pt-BR."""

from __future__ import annotations

import altair as alt
import pandas as pd

from data import MESES, fmt_mes

COR = "#2a78d6"
TEXTO = "#6b6a66"
TEXTO_FORTE = "#9aa7a4"
GRADE = "rgba(128,128,128,0.18)"

_MESES_JS = "[" + ",".join(f"'{m}'" for m in MESES) + "]"
MES = f"{_MESES_JS}[month(datum.value)] + '/' + substring(toString(year(datum.value)), 2)"
COMPACTO = (
    "abs(datum.value) >= 1e6 ? replace(format(datum.value / 1e6, '.2~f'), '.', ',') + ' mi' : "
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


ANO = "toString(year(datum.value))"
TRIMESTRES = ["1º tri", "2º tri", "3º tri", "4º tri"]


def fmt_trimestre(d) -> str:
    return f"{TRIMESTRES[(d.month - 1) // 3]}/{d.year}"


def linha(df: pd.DataFrame, formato, altura: int = 260, trimestral: bool = False):
    """Série mensal: linha suave com degradê, sem pontos; marca o último mês e o mês sob o mouse.

    df tem colunas competencia e valor. O eixo não começa no zero para mostrar a variação.
    """
    rotulo = fmt_trimestre if trimestral else fmt_mes
    dados = df.assign(_mes=df["competencia"].map(rotulo), _valor=df["valor"].map(formato))
    menor, maior = float(df["valor"].min()), float(df["valor"].max())
    folga = (maior - menor) * 0.12 or abs(maior) * 0.05 or 1
    piso = menor - folga
    base = alt.Chart(dados).encode(
        x=alt.X("competencia:T", axis=alt.Axis(labelExpr=ANO if trimestral else MES, grid=False, labelAngle=0,
                                               tickCount={"interval": "year", "step": 1} if trimestral else 6)),
        y=alt.Y("valor:Q", scale=alt.Scale(domain=[piso, maior + folga], nice=False),
                axis=alt.Axis(labelExpr=COMPACTO, tickCount=4)),
    )  # fmt: skip
    degrade = alt.Gradient(
        gradient="linear",
        stops=[alt.GradientStop(color="rgba(42,120,214,0)", offset=0),
               alt.GradientStop(color="rgba(42,120,214,0.28)", offset=1)],
        x1=1, x2=1, y1=1, y2=0,
    )  # fmt: skip
    area = base.mark_area(interpolate="monotone", color=degrade).encode(y2=alt.datum(piso))
    traco = base.mark_line(interpolate="monotone", color=COR, strokeWidth=2.5)

    # ponto e valor só onde o mouse está
    foco = alt.selection_point(nearest=True, on="pointerover", fields=["competencia"], empty=False, clear="pointerout")
    alvo = (
        base.mark_point(size=90, filled=True, color=COR, stroke="white", strokeWidth=1.5)
        .encode(
            opacity=alt.condition(foco, alt.value(1), alt.value(0)),
            tooltip=[alt.Tooltip("_mes:N", title="Mês"), alt.Tooltip("_valor:N", title="Total")],
        )
        .add_params(foco)
    )

    # último mês sempre destacado
    ultimo = base.transform_window(
        ordem="rank()", sort=[alt.SortField("competencia", order="descending")]
    ).transform_filter("datum.ordem == 1")
    fim = ultimo.mark_point(size=70, filled=True, color=COR)
    # o valor do último mês vai no texto abaixo do gráfico (escrito aqui, sobrepunha a linha)
    return _estilo(alt.layer(area, traco, alvo, fim), altura)


def colunas(
    df: pd.DataFrame, x: str, formato, rotulo_x=fmt_mes, altura: int = 260, valores: bool = False, cor: str = COR
):
    """Colunas; com valores=True escreve o valor em cima de cada coluna e esconde o eixo Y."""
    dados = df.assign(_x=df[x].map(rotulo_x), _valor=df["valor"].map(formato))
    if valores:
        base = alt.Chart(dados).encode(
            x=alt.X("_x:O", sort=None, axis=alt.Axis(labelAngle=0, labelFontSize=12)),
            y=alt.Y("valor:Q", axis=None, scale=alt.Scale(domainMin=0, nice=False, padding=18)),
            tooltip=[alt.Tooltip("_x:N", title="Ano"), alt.Tooltip("_valor:N", title="Total")],
        )
        barras = base.mark_bar(color=cor, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=26)
        texto = base.mark_text(dy=-8, fontSize=12, fontWeight="bold", color=TEXTO_FORTE).encode(text="_valor:N")
        return _estilo(alt.layer(barras, texto), altura)
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


CINZA = "rgba(150,155,165,0.45)"
DESTAQUE = "#f2a03d"


def dispersao(df: pd.DataFrame, x: str, y: str, rotulo: str, destaque: str, titulo_x: str, titulo_y: str,
              altura: int = 230):  # fmt: skip
    """Cada estado é um ponto; o estado aberto fica em destaque e os outros viram contexto cinza.

    Serve para responder "esse estado é fora da curva?" sem precisar de tabela.
    """
    dados = df.assign(_destaque=df[rotulo] == destaque)
    base = alt.Chart(dados).encode(
        x=alt.X(f"{x}:Q", axis=alt.Axis(labelExpr=COMPACTO, tickCount=4, title=titulo_x, titleColor=TEXTO,
                                        titleFontSize=11)),
        y=alt.Y(f"{y}:Q", axis=alt.Axis(labelExpr=COMPACTO, tickCount=4, title=titulo_y, titleColor=TEXTO,
                                        titleFontSize=11)),
        tooltip=[alt.Tooltip(f"{rotulo}:N", title="Estado"), alt.Tooltip(f"{x}:Q", title=titulo_x, format=",.1f"),
                 alt.Tooltip(f"{y}:Q", title=titulo_y, format=",.0f")],
    )  # fmt: skip
    outros = base.transform_filter("datum._destaque == false").mark_circle(size=90, color=CINZA)
    aqui = base.transform_filter("datum._destaque").mark_point(size=180, filled=True, color=DESTAQUE, stroke="white",
                                                               strokeWidth=1.5)  # fmt: skip
    nome = (
        base.transform_filter("datum._destaque")
        .mark_text(dy=-16, fontSize=12, fontWeight="bold", color=TEXTO_FORTE)
        .encode(text=f"{rotulo}:N")
    )
    return _estilo(alt.layer(outros, aqui, nome), altura)


def colunas_comparadas(df: pd.DataFrame, x: str, serie: str, formato, altura: int = 200):
    """Duas séries lado a lado (o estado e o Brasil) para ver onde ele foge da média."""
    dados = df.assign(_valor=df["valor"].map(formato))
    chart = (
        alt.Chart(dados)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{x}:O", sort=None, axis=alt.Axis(labelAngle=0, labelFontSize=12)),
            xOffset=alt.XOffset(f"{serie}:N", sort=None),
            y=alt.Y("valor:Q", axis=alt.Axis(labelExpr=COMPACTO, tickCount=4)),
            color=alt.Color(
                f"{serie}:N",
                sort=None,
                scale=alt.Scale(range=[COR, CINZA]),
                legend=alt.Legend(
                    orient="top", direction="horizontal", title=None, labelColor=TEXTO, labelFontSize=12, offset=2
                ),
            ),
            tooltip=[
                alt.Tooltip(f"{x}:N", title="Faixa"),
                alt.Tooltip(f"{serie}:N", title=""),
                alt.Tooltip("_valor:N", title="Valor"),
            ],
        )  # fmt: skip
    )
    return _estilo(chart, altura)

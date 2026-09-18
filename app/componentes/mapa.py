"""Mapa do Brasil clicável (Streamlit custom component v2, sem dependências externas)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from geo import estados

_PASTA = Path(__file__).parent
_componente = st.components.v2.component(
    "mapa_brasil",
    css=(_PASTA / "mapa.css").read_text(),
    js=(_PASTA / "mapa.js").read_text(),
)


AZUL = ["#cde2fb", "#184f95"]  # aba das operadoras
ROXO = ["#ded7f7", "#5b49b8"]  # aba dos estados: outra cor para não confundir as duas leituras


def mapa_brasil(
    valores: dict[str, dict],
    selecionado: str | None,
    key: str,
    on_clique,
    paleta: list[str] = AZUL,
    legenda: tuple[str, str] = ("menos", "mais"),
) -> None:
    """valores: {uf: {"nome", "valor" (define a cor), "texto" (dica)}}. O clique chega em st.session_state[key]["clique"]."""
    _componente(
        data={"geo": estados(), "valores": valores, "selecionado": selecionado,
              "paleta": paleta, "legenda": list(legenda)},
        key=key,
        on_clique_change=on_clique,
    )  # fmt: skip

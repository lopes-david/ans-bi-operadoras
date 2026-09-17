"""Leitura em palavras dos índices da ANS (a mesma régua na lista e na ficha)."""

from __future__ import annotations

import pandas as pd

QUALIDADE = ["Muito boa", "Boa", "Regular", "Ruim", "Muito ruim"]
RECLAMACOES = ["Menos que a média", "Mais que a média"]
SEM_NOTA = "Sem nota"
SEM_INDICE = "Sem índice"
# versão curta para a lista (a ficha usa a frase completa)
RECLAMACOES_CURTO = {
    "Bem menos que a média": "Bem abaixo",
    "Menos que a média": "Abaixo",
    "Mais que a média": "Acima",
    "Bem mais que a média": "Bem acima",
}


def qualidade(nota) -> tuple[str, str] | None:
    """Faixas de nota usadas pela ANS para o IDSS -> (texto, cor)."""
    if nota is None or pd.isna(nota):
        return None
    for limite, texto, cor in ((0.8, "Muito boa", "green"), (0.6, "Boa", "green"), (0.4, "Regular", "orange"),
                               (0.2, "Ruim", "red"), (0.0, "Muito ruim", "red")):  # fmt: skip
        if nota >= limite:
            return texto, cor
    return None


def reclamacoes(igr, mediana) -> tuple[str, str] | None:
    """IGR comparado à mediana das operadoras parecidas -> (texto, cor)."""
    if igr is None or pd.isna(igr) or mediana is None or pd.isna(mediana) or not mediana:
        return None
    if igr <= mediana * 0.5:
        return "Bem menos que a média", "green"
    if igr <= mediana:
        return "Menos que a média", "green"
    if igr <= mediana * 2:
        return "Mais que a média", "orange"
    return "Bem mais que a média", "red"


def grupo_reclamacoes(texto: str | None) -> str | None:
    """Agrupa as 4 leituras nas 2 opções do filtro."""
    if not texto:
        return None
    return "Menos que a média" if "menos" in texto.lower() else "Mais que a média"

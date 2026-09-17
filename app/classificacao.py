"""Leitura em palavras dos índices da ANS, com semáforo (a mesma régua na lista, nos filtros e na ficha)."""

from __future__ import annotations

import pandas as pd

SEMAFORO = {"green": "🟢", "yellow": "🟡", "red": "🔴", None: "⚪"}

QUALIDADE = ["Muito boa", "Boa", "Regular", "Ruim", "Muito ruim"]
COR_QUALIDADE = {"Muito boa": "green", "Boa": "green", "Regular": "yellow", "Ruim": "red", "Muito ruim": "red"}
SEM_NOTA = "Sem nota"

# reclamações: leitura completa (ficha) -> curta (lista)
RECLAMACOES_CURTO = {
    "Muito poucas reclamações": "Muito poucas",
    "Poucas reclamações": "Poucas",
    "Reclamações acima da média": "Acima da média",
    "Muitas reclamações": "Muitas",
}
# as 2 opções do filtro
RECLAMACOES = ["Poucas", "Acima da média"]
SEM_INDICE = "Sem dados"


def qualidade(nota) -> tuple[str, str] | None:
    """Faixas de nota usadas pela ANS para o IDSS -> (texto, cor)."""
    if nota is None or pd.isna(nota):
        return None
    for limite, texto in ((0.8, "Muito boa"), (0.6, "Boa"), (0.4, "Regular"), (0.2, "Ruim"), (0.0, "Muito ruim")):
        if nota >= limite:
            return texto, COR_QUALIDADE[texto]
    return None


def reclamacoes(igr, mediana) -> tuple[str, str] | None:
    """IGR (reclamações por 100 mil clientes) comparado à mediana das operadoras parecidas -> (texto, cor)."""
    if igr is None or pd.isna(igr) or mediana is None or pd.isna(mediana) or not mediana:
        return None
    if igr <= mediana * 0.5:
        return "Muito poucas reclamações", "green"
    if igr <= mediana:
        return "Poucas reclamações", "green"
    if igr <= mediana * 2:
        return "Reclamações acima da média", "yellow"
    return "Muitas reclamações", "red"


def grupo_reclamacoes(texto: str | None) -> str | None:
    """Agrupa as 4 leituras nas 2 opções do filtro."""
    if not texto or texto not in RECLAMACOES_CURTO:
        return None
    return "Poucas" if texto.startswith(("Muito poucas", "Poucas")) else "Acima da média"


def com_semaforo(texto: str, cor: str | None) -> str:
    return f"{SEMAFORO.get(cor, '⚪')} {texto}"


def rotulo_filtro_qualidade(texto: str) -> str:
    return com_semaforo(texto, COR_QUALIDADE[texto])


def rotulo_filtro_reclamacoes(texto: str) -> str:
    return com_semaforo(texto, "green" if texto == "Poucas" else "red")


MINIMO_RESOLUCAO = 10  # abaixo disso a porcentagem oscila demais


def resolucao(pct, avaliadas) -> tuple[str, str] | None:
    """% de reclamações resolvidas na mediação da ANS -> (texto, cor)."""
    if pct is None or pd.isna(pct) or not avaliadas or avaliadas < MINIMO_RESOLUCAO:
        return None
    if pct >= 95:
        return "Resolve bem", "green"
    if pct >= 90:
        return "Resolve razoavelmente", "yellow"
    return "Resolve pouco", "red"

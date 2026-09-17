"""Contorno dos estados (malha do IBGE) convertido em caminhos SVG.

A projeção é feita aqui, uma única vez, para o navegador só desenhar: nada de biblioteca de mapas.
Fonte: https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?intrarregiao=UF&qualidade=minima
"""

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path

ARQUIVO = Path(__file__).parent / "assets" / "br_uf.json"
LARGURA = 600

# código IBGE da UF -> sigla
IBGE_UF = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI",
    "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}  # fmt: skip


def _mercator(lon: float, lat: float) -> tuple[float, float]:
    return math.radians(lon), -math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _aneis(geometria: dict) -> list[list[list[float]]]:
    if geometria["type"] == "Polygon":
        return geometria["coordinates"]
    return [anel for poligono in geometria["coordinates"] for anel in poligono]


@cache
def estados() -> dict:
    """{'largura', 'altura', 'estados': [{uf, d, cx, cy}]} em coordenadas do viewBox."""
    features = json.loads(ARQUIVO.read_text())["features"]
    projetados = {
        IBGE_UF[f["properties"]["codarea"]]: [[_mercator(*p) for p in anel] for anel in _aneis(f["geometry"])]
        for f in features
    }
    xs = [x for aneis in projetados.values() for anel in aneis for x, _ in anel]
    ys = [y for aneis in projetados.values() for anel in aneis for _, y in anel]
    escala = LARGURA / (max(xs) - min(xs))
    altura = (max(ys) - min(ys)) * escala

    saida = []
    for uf, aneis in projetados.items():
        partes, pontos = [], []
        for anel in aneis:
            coords = [((x - min(xs)) * escala, (y - min(ys)) * escala) for x, y in anel]
            pontos += coords
            partes.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in coords) + "Z")
        cx = sum(x for x, _ in pontos) / len(pontos)
        cy = sum(y for _, y in pontos) / len(pontos)
        saida.append({"uf": uf, "d": "".join(partes), "cx": round(cx, 1), "cy": round(cy, 1)})
    return {"largura": LARGURA, "altura": round(altura, 1), "estados": saida}

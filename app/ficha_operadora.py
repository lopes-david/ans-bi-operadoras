"""Cartão (janela) com as informações de uma operadora, em linguagem simples.

Tudo é consultado pela chave da operadora (registro ANS). A lista só oferece operadoras ativas.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts
from classificacao import qualidade, reclamacoes
from data import UF_NOMES, evolucao_operadora, ficha, fmt_dec, fmt_int, fmt_mes

MODALIDADES = {
    "Medicina de Grupo": "Empresa de planos de saúde",
    "Cooperativa Médica": "Cooperativa de médicos",
    "Cooperativa odontológica": "Cooperativa de dentistas",
    "Odontologia de Grupo": "Empresa de planos odontológicos",
    "Seguradora Especializada em Saúde": "Seguradora de saúde",
    "Autogestão": "Plano próprio de empresa ou categoria",
    "Filantropia": "Entidade filantrópica (ex.: Santa Casa)",
    "Administradora de Benefícios": "Administradora de benefícios",
}
CONTRATACAO = {
    "Coletivo empresarial": "Plano de empresa",
    "Individual ou familiar": "Individual ou familiar",
    "Coletivo por adesão": "Por associação ou sindicato",
    "Outros / não identificado": "Outros",
}
PARTES_IDSS = {
    "IDQS": "Qualidade do atendimento",
    "IDGA": "Acesso à rede (consultas, exames)",
    "IDSM": "Saúde financeira",
    "IDGR": "Gestão e cumprimento de regras",
}


def _md(v: str) -> str:
    """Escapa texto vindo dos dados antes de entrar em Markdown."""
    return "".join("\\" + ch if ch in "\\`*_{}[]()#+-.!|<>~$" else ch for ch in v)


def _texto(v) -> str | None:
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def _endereco(c) -> str | None:
    rua = ", ".join(x for x in [_texto(c.logradouro), _texto(c.numero)] if x)
    partes = [rua, _texto(c.complemento), _texto(c.bairro)]
    cidade = " - ".join(x for x in [_texto(c.cidade), _texto(c.uf_sede)] if x)
    cep = _texto(c.cep)
    if cep and len(cep) == 8:
        cep = f"CEP {cep[:5]}-{cep[5:]}"
    texto = ", ".join(x for x in [*partes, cidade] if x)
    return f"{texto} · {cep}" if texto and cep else texto or None


def _telefone(c) -> str | None:
    tel, ddd = _texto(c.telefone), _texto(c.ddd)
    if not tel:
        return None
    tel = f"{tel[:-4]}-{tel[-4:]}" if len(tel) >= 8 else tel
    return f"({ddd}) {tel}" if ddd else tel


def _cnpj(v) -> str | None:
    v = _texto(v)
    return f"{v[:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:]}" if v and len(v) == 14 else v


def _lista(itens: list[tuple[str, str | None]]) -> str:
    return "\n".join(f"- **{rotulo}:** {_md(valor)}" for rotulo, valor in itens if valor)


def _aba_resumo(c, dados: dict, evo: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    atua = f"clientes em {int(c.ufs_atuacao)} estados" if pd.notna(c.ufs_atuacao) and c.ufs_atuacao > 1 else None
    col1.metric("Clientes", fmt_int(c.clientes_brasil), atua, delta_color="off", delta_arrow="off",
                help="Total de pessoas com plano ativo nesta operadora, em todo o Brasil.")  # fmt: skip
    col2.metric("Sede", _texto(c.cidade) or "–", UF_NOMES.get(c.uf_sede, c.uf_sede), delta_color="off",
                delta_arrow="off")  # fmt: skip

    with col3:
        q = qualidade(c.idss)
        st.metric(
            "Qualidade (IDSS)",
            fmt_dec(c.idss, 2) if q else "Sem nota",
            q[0] if q else None,
            delta_color=q[1] if q else "off",
            delta_arrow="off",
            help="Nota dada pela ANS todo ano, de 0 a 1. Quanto maior, melhor.",
        )
        if not evo["idss"].empty:
            with st.popover("Ver detalhes", icon=":material/insights:", width="stretch"):
                st.markdown("**Nota de qualidade ano a ano**")
                st.altair_chart(
                    charts.colunas(evo["idss"], "ano", lambda v: fmt_dec(v, 2), rotulo_x=str, altura=170),
                    width="stretch",
                )
                if evo["partes_idss"]:
                    st.markdown(f"**Notas por tema** · avaliação {int(c.idss_ano)}")
                    for sigla, nome in PARTES_IDSS.items():
                        nota = evo["partes_idss"].get(sigla)
                        if nota is not None:
                            leitura = (qualidade(nota) or ("",))[0]
                            st.markdown(f"{nome}: **{fmt_dec(nota, 2)}** · {leitura}")
                            st.progress(float(min(max(nota, 0), 1)))

    with col4:
        r = reclamacoes(c.igr, dados["mediana_igr"])
        st.metric(
            "Reclamações (IGR)",
            fmt_dec(c.igr, 1) if r else "Sem índice",
            r[0] if r else None,
            delta_color=r[1] if r else "off",
            delta_arrow="off",
            help="Índice Geral de Reclamações da ANS: reclamações para cada 100 mil clientes. "
            f"Quanto menor, melhor. A média das operadoras parecidas é {fmt_dec(dados['mediana_igr'], 1)}.",
        )
        if not evo["igr"].empty:
            with st.popover("Ver detalhes", icon=":material/insights:", width="stretch"):
                st.markdown("**Índice de reclamações mês a mês** · quanto menor, melhor")
                st.altair_chart(charts.linha(evo["igr"], lambda v: fmt_dec(v, 1), altura=190), width="stretch")
                st.caption(f"Média das operadoras parecidas hoje: {fmt_dec(dados['mediana_igr'], 1)}")

    esquerda, direita = st.columns(2, gap="large")
    with esquerda:
        st.markdown("**Como os clientes contrataram**")
        contr = evo["contratacao"].head(4)
        total = evo["contratacao"]["clientes"].sum()
        if total:
            for coluna, linha in zip(st.columns(len(contr)), contr.itertuples(), strict=True):
                coluna.metric(CONTRATACAO.get(linha.contratacao, linha.contratacao),
                              f"{fmt_dec(100 * linha.clientes / total, 0)}%", f"{fmt_int(linha.clientes)} clientes",
                              delta_color="off", delta_arrow="off")  # fmt: skip
        st.markdown("**Entradas e saídas** · últimos 12 meses")
        entraram, sairam = evo["entraram"], evo["sairam"]
        a, b, c3 = st.columns(3)
        a.metric("Entraram", fmt_int(entraram))
        b.metric("Saíram", fmt_int(sairam))
        if pd.notna(entraram) and pd.notna(sairam):
            saldo = entraram - sairam
            c3.metric("Saldo", f"{'+' if saldo > 0 else ''}{fmt_int(saldo)}",
                      "cresceu" if saldo > 0 else "encolheu" if saldo < 0 else "estável",
                      delta_color="green" if saldo > 0 else "red" if saldo < 0 else "off", delta_arrow="off")  # fmt: skip

    with direita:
        st.markdown("**Do que os clientes mais reclamam** · últimos 12 meses")
        assuntos = dados["assuntos"]
        if assuntos.empty:
            st.caption("Nenhuma reclamação registrada na ANS no último ano.")
        else:
            linhas = "\n".join(f"| {_md(a.assunto)} | {fmt_int(a.reclamacoes)} |" for a in assuntos.itertuples())
            st.markdown(f"| Assunto | Reclamações |\n|---|---:|\n{linhas}")


def _aba_evolucao(evo: dict) -> None:
    st.markdown("**Clientes mês a mês**")
    if evo["clientes"].empty:
        st.caption("Sem histórico de clientes.")
    else:
        st.altair_chart(charts.linha(evo["clientes"], fmt_int, altura=220), width="stretch")
        primeiro, ultimo = evo["clientes"].iloc[0], evo["clientes"].iloc[-1]
        st.caption(f"De {fmt_mes(primeiro.competencia)} a {fmt_mes(ultimo.competencia)}: "
                   f"{fmt_int(primeiro.valor)} → {fmt_int(ultimo.valor)} clientes")  # fmt: skip
    st.markdown("**Reclamações mês a mês** · últimos 24 meses")
    if evo["reclamacoes"].empty:
        st.caption("Nenhuma reclamação registrada na ANS nesse período.")
    else:
        st.altair_chart(charts.colunas(evo["reclamacoes"], "competencia", fmt_int, altura=200), width="stretch")


def _aba_contato(reg: str, c) -> None:
    esquerda, direita = st.columns(2)
    with esquerda:
        st.markdown("**Contato**")
        contato = _lista([("Telefone", _telefone(c)), ("E-mail", _texto(c.email)), ("Endereço", _endereco(c))])
        st.markdown(contato or "Sem contato cadastrado.")
    with direita:
        st.markdown("**Dados cadastrais**")
        ano = str(c.data_registro_ans.year) if pd.notna(c.data_registro_ans) else None
        st.markdown(_lista([("CNPJ", _cnpj(c.cnpj)), ("Registro na ANS", reg), ("Na ANS desde", ano)]))
    st.caption("Fonte: cadastro de operadoras da ANS. Telefone e e-mail são os informados pela operadora à ANS.")


@st.dialog("Sobre a operadora", width="large")
def abrir_ficha(reg: str) -> None:
    dados = ficha(reg)
    c = dados["cadastro"]
    evo = evolucao_operadora(reg, _texto(c.igr_cobertura))

    st.subheader(_md(c.nome), anchor=False)
    descricao = MODALIDADES.get(c.modalidade, c.modalidade)
    st.caption(_md(" · ".join(x for x in [descricao, _texto(c.razao_social)] if x)))

    resumo, evolucao, contato = st.tabs(["Resumo", "Evolução", "Contato"])
    with resumo:
        _aba_resumo(c, dados, evo)
    with evolucao:
        _aba_evolucao(evo)
    with contato:
        _aba_contato(reg, c)

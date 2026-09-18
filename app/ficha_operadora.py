"""Cartão (janela) com as informações de uma operadora, em linguagem simples.

Tudo é consultado pela chave da operadora (registro ANS). A lista só oferece operadoras ativas.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

import charts
from classificacao import MINIMO_RESOLUCAO, RECLAMACOES_CURTO, qualidade, reclamacoes, resolucao
from data import UF_NOMES, evolucao_operadora, ficha, fmt_compact, fmt_dec, fmt_int, fmt_mes

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
CONTRATACAO_CURTO = {  # rótulo curto, explicação
    "Coletivo empresarial": ("Empresa", "plano pelo trabalho"),
    "Individual ou familiar": ("Individual", "contratado direto"),
    "Coletivo por adesão": ("Adesão", "via sindicato/associação"),
    "Outros / não identificado": ("Outros", "não informado"),
}
# assuntos da ANS em palavras do dia a dia (o nome oficial fica na dica)
ASSUNTOS = {
    "Regras para Acesso aos Atendimentos": "Dificuldade para ser atendido",
    "Rol de Procedimentos e Cobertura Contratual": "Exame ou procedimento negado",
    "Rede de Atendimento (rede conveniada)": "Rede de médicos e hospitais",
    "Reembolso": "Reembolso",
    "Prazos Máximos para Atendimento": "Demora para ser atendido",
    "Prazos M¿ximos para Atendimento": "Demora para ser atendido",  # erro de codificação na fonte
    "Suspensão e Rescisão Contratuais": "Plano cancelado ou suspenso",
    "Mensalidade ou Outras Cobranças": "Cobranças e mensalidade",
    "Carência": "Carência",
    "Contratação/Adesão e Vigência Contratual": "Contratação do plano",
    "Portabilidade de Carências": "Troca de plano (portabilidade)",
    "Itens Obrigatórios e Cláusulas Contratuais": "Cláusulas do contrato",
    "Reajuste por Variação de Custos": "Reajuste anual",
    "Coparticipação e Franquia": "Coparticipação",
    "Doença ou Lesão Preexistente, CPT e Agravo": "Doença preexistente",
    "Documentos/Informações Obrigatórias ao Consumidor": "Falta de informação ao cliente",
    "Inclusão de Dependentes do Consumidor": "Inclusão de dependentes",
    "Adaptação ou Migração Contratual": "Mudança de contrato",
    "Reajuste por Mudança de Faixa Etária": "Reajuste por idade",
    "Demitidos, Exonerados e Aposentados": "Plano após demissão ou aposentadoria",
}
ASSUNTOS_NA_FICHA = 5
# temas do IDSS: rótulo curto (botão), cor da linha e o que significa, em linguagem simples
GERAL = "Nota geral"
TEMAS_IDSS = {
    GERAL: ("IDSS", "#3987e5", "Nota final da ANS, que resume os quatro temas abaixo."),
    "Atendimento": ("IDQS", "#d95926", "Qualidade do atendimento: exames, partos, internações e prevenção."),
    "Acesso à rede": ("IDGA", "#199e70", "Facilidade de conseguir consulta, exame e cirurgia na rede do plano."),
    "Saúde financeira": ("IDSM", "#c98500", "Se a operadora tem dinheiro em caixa para honrar os atendimentos."),
    "Regras": ("IDGR", "#d55181", "Se a operadora cumpre as regras da ANS e responde aos clientes."),
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


def _tempo_de_mercado(data_registro) -> tuple[str, str | None]:
    if data_registro is None or pd.isna(data_registro):
        return "–", None
    anos = (pd.Timestamp.today() - pd.Timestamp(data_registro)).days // 365
    texto = "menos de 1 ano" if anos < 1 else "1 ano" if anos == 1 else f"{anos} anos"
    return texto, f"desde {pd.Timestamp(data_registro).year}"


def _nota10(idss) -> str:
    """IDSS (0 a 1) como nota escolar de 0 a 10 ("8,1", "10")."""
    return fmt_dec(idss * 10, 1).removesuffix(",0")


def _quadro(titulo: str, subtitulo: str | None = None, chave: str | None = None):
    """Seção com borda e título: cada tipo de informação no seu quadro."""
    quadro = st.container(border=True, key=f"quadro-{chave or abs(hash(titulo))}")
    quadro.markdown(f"**{titulo}**" + (f" · {subtitulo}" if subtitulo else ""))
    return quadro


def _aba_resumo(c, dados: dict, evo: dict) -> None:
    cima_esq, cima_dir = st.columns(2)
    # --- sobre a empresa -----------------------------------------------------------------------
    with cima_esq, _quadro("Sobre a empresa"):
        col1, col2, col3 = st.columns(3)
        atua = f"clientes em {int(c.ufs_atuacao)} estados" if pd.notna(c.ufs_atuacao) and c.ufs_atuacao > 1 else None
        col1.metric("Clientes", fmt_int(c.clientes_brasil), atua, delta_color="off", delta_arrow="off",
                    help="Total de pessoas com plano ativo nesta operadora, em todo o Brasil.")  # fmt: skip
        col2.metric("Sede", _texto(c.cidade) or "–", UF_NOMES.get(c.uf_sede, c.uf_sede), delta_color="off",
                    delta_arrow="off")  # fmt: skip
        tempo, desde = _tempo_de_mercado(c.data_registro_ans)
        col3.metric("No mercado há", tempo, desde, delta_color="off", delta_arrow="off",
                    help="Tempo desde o registro da operadora na ANS.")  # fmt: skip

    # --- avaliação da ANS ----------------------------------------------------------------------
    with cima_dir, _quadro("Avaliação da ANS"):
        col1, col2, col3 = st.columns(3)
        with col1:
            q = qualidade(c.idss)
            st.metric(
                "Qualidade (IDSS)",
                f"{_nota10(c.idss)} de 10" if q else "—",
                q[0] if q else "sem nota da ANS",
                delta_color=q[1] if q else "gray",
                delta_arrow="off",
                help="Nota de qualidade que a ANS dá todo ano, aqui de 0 a 10 (quanto maior, melhor). "
                "Considera atendimento, acesso à rede, saúde financeira e gestão. "
                f"No índice original da ANS (IDSS, de 0 a 1), a nota é {fmt_dec(c.idss, 2)}.",
            )

        with col2:
            r = reclamacoes(c.igr, dados["mediana_igr"])
            st.metric(
                "Reclamações (IGR)",
                fmt_dec(c.igr, 1) if r else "—",
                RECLAMACOES_CURTO.get(r[0], r[0]) if r else "sem índice da ANS",
                delta_color=r[1] if r else "gray",
                delta_arrow="off",
                help="Índice Geral de Reclamações da ANS: quantas reclamações a operadora recebe para cada "
                "100 mil clientes. Quanto menor, melhor. A média das operadoras parecidas é "
                f"{fmt_dec(dados['mediana_igr'], 1)}.",
            )

        with col3:
            res = resolucao(c.pct_resolvidas, c.nip_avaliadas_12m)
            avaliadas = int(c.nip_avaliadas_12m) if pd.notna(c.nip_avaliadas_12m) else 0
            st.metric(
                "Reclamações resolvidas",
                f"{fmt_dec(c.pct_resolvidas, 0)}%" if res else "—",
                res[0] if res else "poucas para avaliar",
                delta_color=res[1] if res else "gray",
                delta_arrow="off",
                help="Das reclamações feitas à ANS nos últimos 12 meses e já encerradas, quantas a operadora "
                "resolveu direto com o cliente, sem virar processo. "
                + (f"Foram {fmt_int(c.nip_resolvidas_12m)} de {fmt_int(avaliadas)}." if avaliadas else "")
                + f" Só é avaliada com {MINIMO_RESOLUCAO} ou mais reclamações encerradas.",
            )

    fluxo, contratos, queixas = st.columns([5.5, 4, 5.5])
    # --- entradas e saídas -------------------------------------------------------------------
    with fluxo, _quadro("Clientes nos últimos 12 meses", chave="resumo-baixo-1"):
        entraram, sairam = evo["entraram"], evo["sairam"]
        if pd.isna(entraram) or pd.isna(sairam):
            st.caption("Sem dados de entradas e saídas.")
        else:
            saldo = entraram - sairam
            base = c.clientes_brasil if pd.notna(c.clientes_brasil) and c.clientes_brasil else 0
            estavel = base and abs(saldo) < 0.01 * base  # menos de 1% da carteira
            a, b, d = st.columns(3)
            a.metric("Entraram", f"+{fmt_int(entraram)}", "novos clientes", delta_color="green", delta_arrow="up")
            b.metric("Saíram", f"−{fmt_int(sairam)}", "cancelaram", delta_color="red", delta_arrow="down")
            sinal = "+" if saldo > 0 else "−" if saldo < 0 else ""
            if estavel:
                leitura, cor, seta = "ficou estável", "yellow", "off"
            elif saldo > 0:
                leitura, cor, seta = "cresceu", "green", "up"
            else:
                leitura, cor, seta = "encolheu", "red", "down"
            d.metric("Resultado", f"{sinal}{fmt_int(abs(saldo))}", leitura, delta_color=cor, delta_arrow=seta,
                     help="Entradas menos saídas. Variação menor que 1% da carteira conta como estável.")  # fmt: skip
            if evo["transferencia_12m"]:
                quando = fmt_mes(evo["transferencia_12m"]["competencia"])
                st.caption(f"Sem contar a transferência de clientes entre empresas do grupo em {quando}.")

    # --- tipo de contratação -----------------------------------------------------------------
    with contratos, _quadro("Como os clientes contrataram", chave="resumo-baixo-2"):
        contr = evo["contratacao"]
        total = contr["clientes"].sum()
        fatias = [linha for linha in contr.itertuples() if total and linha.clientes / total >= 0.01]  # esconde < 1%
        if not fatias:
            st.caption("Sem dados de contratação.")
        else:
            for col, linha in zip(st.columns(len(fatias)), fatias, strict=True):
                curto, explica = CONTRATACAO_CURTO.get(linha.contratacao, (linha.contratacao, None))
                col.metric(curto, f"{fmt_dec(100 * linha.clientes / total, 0)}%",
                           help=f"{linha.contratacao} ({explica}): {fmt_int(linha.clientes)} clientes.")  # fmt: skip
            st.caption("No plano individual o reajuste anual é limitado pela ANS; nos de empresa e adesão, "
                       "é negociado com a operadora.")  # fmt: skip

    # --- assuntos ------------------------------------------------------------------------------
    assuntos = dados["assuntos"]
    total = assuntos["reclamacoes"].sum() if not assuntos.empty else 0
    subtitulo = f"{fmt_int(total)} no último ano" if total else "último ano"
    with queixas, _quadro("Motivos de reclamação", subtitulo, chave="resumo-baixo-3"):
        if not total:
            st.caption("Nenhuma reclamação registrada na ANS no último ano.")
        else:
            por_tema = (
                assuntos.assign(tema=assuntos["assunto"].map(lambda a: ASSUNTOS.get(a, a)))
                .groupby("tema", as_index=False)["reclamacoes"]
                .sum()
                .sort_values("reclamacoes", ascending=False)
                .head(ASSUNTOS_NA_FICHA)
            )
            st.html(_ranking(por_tema, total))
            st.caption(_frase_reclamacoes(por_tema.iloc[0], total))


def _ranking(por_tema: pd.DataFrame, total) -> str:
    """Lista numerada: posição, motivo e, à direita, quantidade e fatia do total."""
    linhas = "".join(
        f'<li><span class="pos">{i}</span><span class="tema">{escape(t.tema)}</span>'
        f'<span class="qtd"><b>{fmt_int(t.reclamacoes)}</b> · {fmt_dec(100 * t.reclamacoes / total, 0)}%</span></li>'
        for i, t in enumerate(por_tema.itertuples(), 1)
    )
    return f"<ol class='ranking'>{linhas}</ol>"


def _frase_reclamacoes(maior, total) -> str:
    """Resumo em linguagem simples do motivo mais comum ("1 em cada 4 reclamações...")."""
    fatia = maior.reclamacoes / total
    tema = maior.tema[0].lower() + maior.tema[1:]
    if fatia >= 0.9:
        return f"Quase todas as reclamações são sobre {_md(tema)}."
    if fatia >= 0.5:
        return f"Mais da metade das reclamações é sobre {_md(tema)}."
    return f"1 em cada {round(1 / fatia)} reclamações é sobre {_md(tema)}."


ANOS_NO_GRAFICO = 6
ANOS_NA_VARIACAO = 5


def _por_ano(serie: pd.DataFrame, subir_e_bom: bool, titulo: str, ajustes: dict | None = None) -> None:
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


def _nota_parcial(serie: pd.DataFrame) -> str:
    ate = pd.Timestamp(serie.iloc[-1].ate)
    return f" · \\*{ate.year} até {fmt_mes(ate).split('/')[0]}" if ate.month < 12 else ""


def _historico_clientes(evo: dict) -> None:
    serie = evo["clientes_tri"]
    if len(serie) < 4 or not serie["valor"].any():
        st.caption("Ainda não há histórico suficiente.")
        return
    st.altair_chart(charts.linha(serie, fmt_int, altura=150, trimestral=True), width="stretch")
    ajustes = {}
    for salto in evo["saltos"]:
        ano = pd.Timestamp(salto["competencia"]).year
        ajustes[ano] = ajustes.get(ano, 0) + salto["variacao"]
    _por_ano(
        evo["clientes_ano"], subir_e_bom=True, titulo="Clientes a mais ou a menos que no ano anterior:", ajustes=ajustes
    )
    texto = _nota_parcial(evo["clientes_ano"]).removeprefix(" · ")
    if evo["saltos"]:
        # a transferência de carteira não é crescimento real: fica fora das % e é explicada
        salto = evo["saltos"][-1]
        outra = (salto["contraparte"] or "").rstrip(".")
        de = f" {'da' if salto['variacao'] > 0 else 'para a'} {_md(outra)}" if outra else ""
        verbo = "recebeu" if salto["variacao"] > 0 else "passou"
        texto += (f"  \nO degrau de {fmt_mes(salto['competencia'])} é transferência de carteira: "
                  f"{verbo} {fmt_compact(abs(salto['variacao']))} clientes{de}.")  # fmt: skip
    st.caption(texto)


def _historico_qualidade(c, evo: dict, reg: str) -> None:
    """Colunas por ano da nota escolhida: a geral ou um dos quatro temas que a compõem."""
    escolha = st.session_state.get(f"tema-{reg}") or GERAL
    sigla, cor, explicacao = TEMAS_IDSS[escolha]
    if sigla == "IDSS":
        serie = evo["idss"]
    else:
        temas = evo["temas_idss"]
        serie = temas[temas["indicador"] == sigla][["ano", "valor"]]
    if serie.empty:
        st.caption("A ANS não publicou essa nota para esta operadora.")
    else:
        notas = serie.tail(ANOS_NO_GRAFICO).assign(valor=lambda d: d["valor"] * 10)
        st.altair_chart(charts.colunas(notas, "ano", _nota_texto, rotulo_x=str, altura=150, valores=True, cor=cor),
                        width="stretch")  # fmt: skip
    st.pills("Tema", list(TEMAS_IDSS), default=GERAL, key=f"tema-{reg}", label_visibility="collapsed")
    st.caption(f"{explicacao} Nota de 0 a 10.")


def _nota_texto(v) -> str:
    return fmt_dec(v, 1).removesuffix(",0")


def _historico_reclamacoes(evo: dict, mediana) -> None:
    serie = evo["igr_tri"]
    if len(serie) < 2:
        st.caption("A ANS não publicou índice de reclamações para esta operadora.")
        return
    st.altair_chart(charts.linha(serie, lambda v: fmt_dec(v, 1), altura=150, trimestral=True), width="stretch")
    _por_ano(evo["igr_ano"], subir_e_bom=False, titulo="Reclamações a mais ou a menos que no ano anterior:")
    atual = serie.iloc[-1]
    st.caption(f"{_nota_parcial(evo['igr_ano']).removeprefix(' · ')}  \n"
               f"Último trimestre: **{fmt_dec(atual.valor, 1)}** · média do mercado: {fmt_dec(mediana, 1)} "
               "(reclamações a cada 100 mil clientes)")  # fmt: skip


def _aba_historico(c, dados: dict, evo: dict, reg: str) -> None:
    clientes, notas, queixas = st.columns(3)
    with clientes, _quadro("Evolução dos clientes"):
        _historico_clientes(evo)
    with notas, _quadro("Nota de qualidade por ano"):
        _historico_qualidade(c, evo, reg)
    with queixas, _quadro("Evolução das reclamações"):
        _historico_reclamacoes(evo, dados["mediana_igr"])


def _aba_contato(reg: str, c) -> None:
    esquerda, direita = st.columns(2)
    with esquerda, _quadro("Contato"):
        contato = _lista([("Telefone", _telefone(c)), ("E-mail", _texto(c.email)), ("Endereço", _endereco(c))])
        st.markdown(contato or "Sem contato cadastrado.")
    with direita, _quadro("Dados cadastrais"):
        ano = str(c.data_registro_ans.year) if pd.notna(c.data_registro_ans) else None
        st.markdown(_lista([("CNPJ", _cnpj(c.cnpj)), ("Registro na ANS", reg), ("Na ANS desde", ano)]))
    st.caption("Fonte: cadastro de operadoras da ANS. Telefone e e-mail são os informados pela operadora à ANS.")


def _conteudo_ficha(reg: str) -> None:
    dados = ficha(reg)
    c = dados["cadastro"]
    evo = evolucao_operadora(reg, _texto(c.igr_cobertura))
    with st.container(key="ficha"):
        descricao = MODALIDADES.get(c.modalidade, c.modalidade)
        st.caption(_md(" · ".join(x for x in [descricao, _texto(c.razao_social)] if x)))
        resumo, historico, contato = st.tabs(["Resumo", "Histórico", "Contato"])
        with resumo:
            _aba_resumo(c, dados, evo)
        with historico:
            _aba_historico(c, dados, evo, reg)
        with contato:
            _aba_contato(reg, c)


def fechar_ficha() -> None:
    st.session_state.pop("_ficha", None)


def abrir_ficha(reg: str) -> None:
    """Abre a janela com o nome da operadora no título.

    A ficha é redesenhada a cada interação interna (o seletor de temas), por isso quem fecha
    de verdade é o `on_dismiss`.
    """
    nome = ficha(reg)["cadastro"].nome
    st.dialog(nome, width="large", on_dismiss=fechar_ficha)(_conteudo_ficha)(reg)

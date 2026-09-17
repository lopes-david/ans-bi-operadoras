"""Smoke test do painel sobre a gold gerada pelas fixtures."""

import sys
from pathlib import Path

import pytest

from ans_bi import gold, pipeline
from tests.test_pipeline import TASKS

testing = pytest.importorskip("streamlit.testing.v1")

APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture
def app(env, monkeypatch):
    settings, lake = env
    for t in TASKS:
        pipeline.run_task(settings, lake, t)
    gold.build(settings, lake)
    monkeypatch.setenv("ANS_GOLD_URI", lake.uri("gold"))
    monkeypatch.syspath_prepend(str(APP))
    yield lambda: testing.AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30)
    for mod in ("data", "charts", "geo", "componentes", "componentes.mapa"):
        sys.modules.pop(mod, None)


def test_inicio_sem_estado(app):
    at = app().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.subheader[0].value == "Escolha um estado"
    assert at.metric[0].value == "2"  # operadoras ativas com clientes


def test_operadoras_pela_sede(app):
    # ALFA tem sede em SP; BETA tem sede no RJ mas clientes em SP
    at = app().run()
    at.selectbox(key="uf").set_value("SP").run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.subheader[0].value == "São Paulo"
    assert list(at.dataframe[0].value["nome"]) == ["ALFA"]
    assert list(at.dataframe[0].value["clientes"]) == [30]  # total no Brasil

    at.selectbox(key="uf").set_value("RJ").run()
    assert list(at.dataframe[0].value["nome"]) == ["BETA ODONTO S.A."]


def test_estado_pela_url_e_limpar(app):
    at = app()
    at.query_params["uf"] = "SP"
    at.run()
    assert at.subheader[0].value == "São Paulo"
    at.button(key="fechar").click().run()
    assert at.subheader[0].value == "Escolha um estado"


def test_filtrar_por_cidade_e_buscar(app):
    at = app()
    at.query_params["uf"] = "SP"
    at.run()
    cidade = at.selectbox(key="cidade-SP")
    assert cidade.options == ["Todas", "São Paulo"]
    cidade.set_value("São Paulo").run()
    assert list(at.dataframe[0].value["nome"]) == ["ALFA"]
    at.text_input(key="busca-SP").input("xyz").run()
    assert at.dataframe[0].value.empty
    assert not at.exception


def test_ficha_da_operadora(app):
    at = app()
    at.session_state["_abrir"] = "111111"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    rotulos = [m.label for m in at.metric]
    assert {"Clientes", "Sede", "No mercado há", "Qualidade (IDSS)", "Reclamações (IGR)",
            "Reclamações resolvidas"} <= set(rotulos)  # fmt: skip
    fluxo = {m.label: m for m in at.metric if m.label in ("Entraram", "Saíram", "Resultado")}
    assert fluxo["Entraram"].value == "+1" and fluxo["Saíram"].value == "−1"
    assert fluxo["Resultado"].delta == "ficou estável"  # fixture: 1 entrada e 1 saída no último ano
    mercado = next(m for m in at.metric if m.label == "No mercado há")
    assert mercado.value.endswith("anos")  # registro em 2001
    resolvidas = next(m for m in at.metric if m.label == "Reclamações resolvidas")
    assert (resolvidas.value, resolvidas.delta) == ("—", "poucas para avaliar")
    assert [t.label for t in at.tabs] == ["Resumo", "Histórico", "Contato"]
    textos = " ".join(m.value for m in at.markdown)
    assert "**Sobre a empresa**" in textos and "**Avaliação da ANS**" in textos
    assert "11\\.111\\.111/0001\\-11" in textos  # CNPJ formatado (escapado para Markdown)
    assert "exame ou procedimento negado" in " ".join(c.value for c in at.caption)
    assert "\\(11\\) 1111" in textos  # telefone (escapado para Markdown)
    assert next(m for m in at.metric if m.label == "Qualidade (IDSS)").value == "8,1 de 10"


def test_filtros_de_qualidade_e_ordem(app):
    at = app()
    at.query_params["uf"] = "SP"
    at.run()
    tabela = at.dataframe[0].value
    assert list(tabela["qualidade"]) == ["🟢"]  # IDSS 0,81 = muito boa
    assert list(tabela["reclamacoes"]) == ["⚪"]  # sem operadoras de referência nas fixtures

    at.multiselect(key="f_qualidade").set_value(["Ruim"]).run()
    assert at.dataframe[0].value.empty
    assert "**0** operadoras" in " ".join(m.value for m in at.markdown)

    at.multiselect(key="f_qualidade").set_value(["Muito boa", "Boa"]).run()
    for ordem in (
        ["melhor_qualidade"],
        ["pior_qualidade", "mais_reclamacoes"],
        ["menos_reclamacoes", "melhor_qualidade", "pior_qualidade"],
        ["clientes", "mais_reclamacoes"],
    ):
        at.multiselect(key="ordem").set_value(ordem).run()
        assert not at.exception, [e.value for e in at.exception]
        assert list(at.dataframe[0].value["nome"]) == ["ALFA"]


def test_semaforo_de_reclamacoes():
    import importlib

    sys.path.insert(0, str(APP))
    try:
        c = importlib.import_module("classificacao")
    finally:
        sys.path.remove(str(APP))
    assert c.reclamacoes(10, 24) == ("Muito poucas reclamações", "green")
    assert c.reclamacoes(27, 24.4) == ("Reclamações acima da média", "yellow")  # caso da Unimed Porto Alegre
    assert c.reclamacoes(100, 24) == ("Muitas reclamações", "red")
    assert c.grupo_reclamacoes("Poucas reclamações") == "Poucas"
    assert c.grupo_reclamacoes("Muitas reclamações") == "Acima da média"
    assert c.qualidade(0.5) == ("Regular", "yellow")
    # odontológicas: a referência é a média (0,53), não a mediana zero
    assert c.reclamacoes(0, 0.53) == ("Muito poucas reclamações", "green")
    assert c.reclamacoes(0.8, 0.53) == ("Reclamações acima da média", "yellow")


def test_semaforo_de_resolucao():
    sys.path.insert(0, str(APP))
    try:
        import classificacao as c
    finally:
        sys.path.remove(str(APP))
    assert c.resolucao(97.0, 500) == ("Resolve bem", "green")
    assert c.resolucao(92.0, 500) == ("Resolve razoavelmente", "yellow")
    assert c.resolucao(80.0, 500) == ("Resolve pouco", "red")
    assert c.resolucao(50.0, 3) is None  # poucas reclamações para avaliar

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
    assert cidade.options == ["Todas as cidades", "São Paulo"]
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
    assert {"Clientes", "Sede", "Qualidade (IDSS)", "Reclamações (IGR)", "Entraram", "Saíram"} <= set(rotulos)
    assert [t.label for t in at.tabs] == ["Resumo", "Evolução", "Contato"]
    textos = " ".join(m.value for m in at.markdown)
    assert "11\\.111\\.111/0001\\-11" in textos  # CNPJ formatado (escapado para Markdown)
    assert "Rol de Procedimentos" in textos
    assert "\\(11\\) 1111" in textos  # telefone (escapado para Markdown)
    assert next(m for m in at.metric if m.label == "Qualidade (IDSS)").value == "0,81"


def test_filtros_de_qualidade_e_ordem(app):
    at = app()
    at.query_params["uf"] = "SP"
    at.run()
    tabela = at.dataframe[0].value
    assert list(tabela["qualidade"]) == ["Muito boa"]  # IDSS 0,81
    assert list(tabela["reclamacoes"]) == ["Sem índice"]  # sem operadoras de referência nas fixtures

    at.multiselect(key="f_qualidade").set_value(["Ruim"]).run()
    assert at.dataframe[0].value.empty
    assert "**0** operadoras" in " ".join(m.value for m in at.markdown)

    at.multiselect(key="f_qualidade").set_value(["Muito boa", "Boa"]).run()
    for ordem in ["melhor_qualidade", "pior_qualidade", "menos_reclamacoes", "mais_reclamacoes"]:
        at.selectbox(key="ordem").set_value(ordem).run()
        assert not at.exception, [e.value for e in at.exception]
        assert list(at.dataframe[0].value["nome"]) == ["ALFA"]

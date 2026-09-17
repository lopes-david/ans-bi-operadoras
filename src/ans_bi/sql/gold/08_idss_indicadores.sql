-- IDSS e dimensões (IDQS, IDGA, IDSM, IDGR) em formato longo, deduplicado entre arquivos.
SELECT
    registro_ans,
    indicador,
    ano_avaliacao,
    any_value(ano_base) AS ano_base,
    max(valor)          AS valor
FROM idss
WHERE indicador IN ('IDSS', 'IDQS', 'IDGA', 'IDSM', 'IDGR')
GROUP BY registro_ans, indicador, ano_avaliacao

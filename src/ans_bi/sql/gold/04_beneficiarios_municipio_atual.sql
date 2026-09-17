-- Distribuição geográfica na competência mais recente (para mapas e tabelas por município).
SELECT
    registro_ans,
    uf,
    cd_municipio,
    any_value(nm_municipio) AS municipio,
    CASE WHEN cobertura ILIKE 'odonto%' THEN 'Odontológico' ELSE 'Médico-hospitalar' END AS cobertura,
    sum(qt_ativos)::INTEGER AS beneficiarios
FROM beneficiarios_municipio
WHERE competencia = (SELECT max(competencia) FROM beneficiarios_municipio)
GROUP BY registro_ans, uf, cd_municipio, 5
HAVING sum(qt_ativos) > 0

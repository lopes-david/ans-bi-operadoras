-- Pirâmide etária da carteira na competência mais recente.
SELECT
    registro_ans,
    uf,
    CASE WHEN cobertura ILIKE 'odonto%' THEN 'Odontológico' ELSE 'Médico-hospitalar' END AS cobertura,
    sexo,
    faixa_etaria,
    sum(qt_ativos)::INTEGER AS beneficiarios
FROM beneficiarios_perfil
WHERE competencia = (SELECT max(competencia) FROM beneficiarios_perfil)
GROUP BY ALL
HAVING sum(qt_ativos) > 0

-- Vidas por operadora x UF x cobertura x tipo de contratação, por competência.
SELECT
    strptime(competencia, '%Y-%m')::DATE AS competencia,
    registro_ans,
    uf,
    CASE WHEN cobertura ILIKE 'odonto%' THEN 'Odontológico' ELSE 'Médico-hospitalar' END AS cobertura,
    CASE
        WHEN contratacao ILIKE 'individual%'   THEN 'Individual ou familiar'
        WHEN contratacao ILIKE '%empresarial%' THEN 'Coletivo empresarial'
        WHEN contratacao ILIKE '%ades%'        THEN 'Coletivo por adesão'
        ELSE 'Outros / não identificado'
    END AS contratacao,
    sum(qt_ativos)::INTEGER     AS beneficiarios,
    sum(qt_aderidos)::INTEGER   AS aderidos,
    sum(qt_cancelados)::INTEGER AS cancelados
FROM beneficiarios_municipio
GROUP BY ALL
HAVING sum(qt_ativos) > 0 OR sum(qt_aderidos) > 0 OR sum(qt_cancelados) > 0

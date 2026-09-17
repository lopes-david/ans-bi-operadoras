-- IGR mensal por operadora e cobertura.
SELECT DISTINCT
    competencia,
    registro_ans,
    cobertura,
    porte,
    igr,
    qt_reclamacoes,
    qt_beneficiarios
FROM igr
WHERE competencia IS NOT NULL

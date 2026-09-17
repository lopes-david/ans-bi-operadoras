-- Índice Geral de Reclamações (IGR, versão 2023): reclamações por 100 mil beneficiários.
SELECT
    lpad(trim(REGISTRO_OPERADORA), 6, '0')                       AS registro_ans,
    COBERTURA                                                    AS cobertura,
    TRY_CAST(replace(IGR, ',', '.') AS DOUBLE)                   AS igr,
    TRY_CAST(QTD_RECLAMACOES AS INTEGER)                         AS qt_reclamacoes,
    TRY_CAST(QTD_BENEFICIARIOS AS INTEGER)                       AS qt_beneficiarios,
    PORTE_OPERADORA                                              AS porte,
    TRY_CAST(strptime(COMPETENCIA, '%Y-%m') AS DATE)             AS competencia,
    TRY_CAST(strptime(COMPETENCIA_BENEFICIARIO, '%Y-%m') AS DATE) AS competencia_beneficiario,
    TRY_CAST(DT_ATUALIZACAO AS DATE)                             AS data_atualizacao
FROM {src}
WHERE REGISTRO_OPERADORA IS NOT NULL

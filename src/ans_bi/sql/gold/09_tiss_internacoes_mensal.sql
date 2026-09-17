-- Internações (TISS) por UF do prestador, modalidade e porte da operadora.
SELECT
    competencia_evento                     AS competencia,
    uf_prestador                           AS uf,
    modalidade,
    porte,
    sum(qt_internacoes)::BIGINT            AS internacoes,
    sum(dias_permanencia)::BIGINT          AS dias_permanencia,
    sum(diarias_uti)::BIGINT               AS diarias_uti
FROM tiss_hospitalar
WHERE competencia_evento IS NOT NULL
GROUP BY ALL

-- Internações (TISS) por UF do prestador, perfil do paciente e tipo de internação.
-- A ANS publica este dado sem identificar a operadora: só dá para analisar somado por estado.
-- tipo_internacao (tabela 51 do TISS): 1 clínica, 2 cirúrgica, 3 obstétrica, 4 pediátrica, 5 psiquiátrica.
-- carater_atendimento (tabela 50): 1 eletivo, 2 urgência/emergência.
SELECT
    competencia_evento                     AS competencia,
    uf_prestador                           AS uf,
    faixa_etaria,
    sexo,
    modalidade,
    porte,
    tipo_internacao,
    carater_atendimento,
    sum(qt_internacoes)::BIGINT            AS internacoes,
    sum(dias_permanencia)::BIGINT          AS dias_permanencia,
    sum(diarias_uti)::BIGINT               AS diarias_uti
FROM tiss_hospitalar
WHERE competencia_evento IS NOT NULL
GROUP BY ALL

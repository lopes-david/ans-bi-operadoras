-- TISS hospitalar (internações). Os dados não trazem a operadora (só plano anonimizado),
-- então a agregação é por município do prestador, modalidade e porte.
SELECT
    TRY_CAST(strptime(ANO_MES_EVENTO, '%Y-%m') AS DATE)   AS competencia_evento,
    UF_PRESTADOR                                          AS uf_prestador,
    CD_MUNICIPIO_PRESTADOR                                AS cd_municipio_prestador,
    NM_MODALIDADE                                         AS modalidade,
    PORTE                                                 AS porte,
    FAIXA_ETARIA                                          AS faixa_etaria,
    SEXO                                                  AS sexo,
    CD_CARATER_ATENDIMENTO                                AS carater_atendimento,
    CD_TIPO_INTERNACAO                                    AS tipo_internacao,
    count(*)::INTEGER                                     AS qt_internacoes,
    sum(TRY_CAST(TEMPO_DE_PERMANENCIA AS INTEGER))::BIGINT AS dias_permanencia,
    sum(TRY_CAST(QT_DIARIA_UTI AS INTEGER))::BIGINT        AS diarias_uti
FROM {src}
GROUP BY ALL

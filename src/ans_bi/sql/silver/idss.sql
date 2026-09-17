-- IDSS histórico: o arquivo é "largo" (uma coluna por indicador x ano). Aqui vira formato longo.
-- Colunas no padrão <INDICADOR>_<ano_avaliacao>_<ano_base>, ex.: IDSS_2025_2024.
WITH longo AS (
    UNPIVOT (SELECT * FROM {src})
    ON COLUMNS('^ID')
    INTO NAME coluna VALUE valor
)
SELECT
    lpad(trim(REGISTRO_OPERADORA), 6, '0')                              AS registro_ans,
    regexp_extract(coluna, '^([A-Z]+)_', 1)                             AS indicador,
    TRY_CAST(regexp_extract(coluna, '_(\d{4})_+\d{4}$', 1) AS SMALLINT) AS ano_avaliacao,
    TRY_CAST(regexp_extract(coluna, '_(\d{4})$', 1) AS SMALLINT)        AS ano_base,
    TRY_CAST(replace(valor, ',', '.') AS DOUBLE)                        AS valor
FROM longo
WHERE TRY_CAST(replace(valor, ',', '.') AS DOUBLE) IS NOT NULL

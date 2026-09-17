-- Beneficiários consolidados (ICB) agregados sem o código do plano, que é a coluna de
-- maior cardinalidade: reduz o volume em ~10x mantendo operadora x município x contratação.
SELECT
    strptime(ID_CMPT_MOVEL, '%Y-%m')::DATE       AS competencia,
    lpad(trim(CD_OPERADORA), 6, '0')              AS registro_ans,
    SG_UF                                         AS uf,
    CD_MUNICIPIO                                  AS cd_municipio,
    any_value(NM_MUNICIPIO)                       AS nm_municipio,
    DE_CONTRATACAO_PLANO                          AS contratacao,
    COBERTURA_ASSIST_PLAN                         AS cobertura,
    sum(TRY_CAST(QT_BENEFICIARIO_ATIVO AS INTEGER))::INTEGER    AS qt_ativos,
    sum(TRY_CAST(QT_BENEFICIARIO_ADERIDO AS INTEGER))::INTEGER  AS qt_aderidos,
    sum(TRY_CAST(QT_BENEFICIARIO_CANCELADO AS INTEGER))::INTEGER AS qt_cancelados
FROM {src}
GROUP BY competencia, registro_ans, uf, cd_municipio, contratacao, cobertura

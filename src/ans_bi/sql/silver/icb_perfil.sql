-- Perfil demográfico da carteira (sexo x faixa etária) por operadora e UF.
SELECT
    strptime(ID_CMPT_MOVEL, '%Y-%m')::DATE       AS competencia,
    lpad(trim(CD_OPERADORA), 6, '0')              AS registro_ans,
    SG_UF                                         AS uf,
    TP_SEXO                                       AS sexo,
    DE_FAIXA_ETARIA                               AS faixa_etaria,
    COBERTURA_ASSIST_PLAN                         AS cobertura,
    TIPO_VINCULO                                  AS tipo_vinculo,
    sum(TRY_CAST(QT_BENEFICIARIO_ATIVO AS INTEGER))::INTEGER AS qt_ativos
FROM {src}
GROUP BY ALL

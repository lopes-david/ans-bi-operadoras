-- Demandas NIP (reclamações de consumidores), uma linha por demanda.
-- Nomes de operadora ficam na dimensão; aqui só a chave.
SELECT
    TRY_CAST(NUMERO_DA_DEMANDA AS BIGINT)                          AS numero_demanda,
    TRY_CAST(ABERTURA_DA_DEMANDA AS DATE)                          AS data_abertura,
    make_date(TRY_CAST(ANO_DE_REFERENCIA AS INTEGER),
              TRY_CAST(MES_DE_REFERENCIA AS INTEGER), 1)           AS competencia,
    SITUACAO_DA_DEMANDA                                            AS situacao_demanda,
    FORMA_DE_CONTATO_COM_A_ANS                                     AS forma_contato,
    ASSUNTO                                                        AS assunto,
    -- 1º nível é quase sempre "Produto ou Plano"; o 2º (Cobertura, Reajustes...) é o que informa
    coalesce(nullif(trim(split_part(ASSUNTO, '>>', 2)), ''), trim(split_part(ASSUNTO, '>>', 1))) AS assunto_grupo,
    lpad(trim(REGISTRO_OPERADORA), 6, '0')                         AS registro_ans,
    MODALIDADE_DA_OPERADORA                                        AS modalidade,
    TIPO_DE_PLANO_CONTRATADO                                       AS tipo_plano,
    EPOCA_DE_ADESAO_AO_PLANO                                       AS epoca_adesao,
    TIPOS_DE_COBER_CONTRATADAS                                     AS cobertura,
    TRY_CAST(IDADE_BENEFICIARIO AS SMALLINT)                       AS idade,
    SEXO                                                           AS sexo,
    ESTADO_DO_BENEFICIARIO                                         AS uf_beneficiario,
    MUNIC_CONSUMIDOR_ATEND                                         AS cd_municipio_beneficiario,
    CLASSIFICACAO_DA_NIP                                           AS classificacao_nip,
    NATUREZA_DA_NIP                                                AS natureza_nip,
    SITUACAO_DA_NIP                                                AS situacao_nip,
    RESPOSTA_BENEFICIARIO                                          AS resposta_beneficiario
FROM {src}
WHERE REGISTRO_OPERADORA IS NOT NULL

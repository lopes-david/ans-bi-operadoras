-- Cadastro de operadoras (ativas ou canceladas), com endereço e contato institucional.
-- Um snapshot por dia preserva o histórico, já que a ANS publica apenas a "foto" atual.
-- Nomes de representantes legais são descartados (dado pessoal, sem uso no BI).
SELECT
    lpad(trim(REGISTRO_OPERADORA), 6, '0')          AS registro_ans,
    regexp_replace(CNPJ, '[^0-9]', '', 'g')         AS cnpj,
    trim(RAZAO_SOCIAL)                              AS razao_social,
    nullif(trim(NOME_FANTASIA), '')                 AS nome_fantasia,
    trim(MODALIDADE)                                AS modalidade,
    nullif(trim(LOGRADOURO), '')                    AS logradouro,
    nullif(trim(NUMERO), '')                        AS numero,
    nullif(trim(COMPLEMENTO), '')                   AS complemento,
    nullif(trim(BAIRRO), '')                        AS bairro,
    trim(CIDADE)                                    AS cidade,
    upper(trim(UF))                                 AS uf,
    nullif(regexp_replace(CEP, '[^0-9]', '', 'g'), '')      AS cep,
    nullif(regexp_replace(DDD, '[^0-9]', '', 'g'), '')      AS ddd,
    nullif(regexp_replace(TELEFONE, '[^0-9]', '', 'g'), '') AS telefone,
    nullif(lower(trim(ENDERECO_ELETRONICO)), '')            AS email,
    TRY_CAST(REGIAO_DE_COMERCIALIZACAO AS TINYINT)  AS regiao_comercializacao,
    TRY_CAST(DATA_REGISTRO_ANS AS DATE)             AS data_registro_ans,
    {cancel_cols}
FROM {src}
WHERE REGISTRO_OPERADORA IS NOT NULL

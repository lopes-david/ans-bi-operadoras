-- Dimensão de operadoras: último snapshot de ativas + canceladas (ativa tem prioridade).
WITH ultimo AS (
    SELECT situacao, max(snapshot) AS snapshot FROM operadoras GROUP BY situacao
),
cadastro AS (
    SELECT o.*,
           row_number() OVER (PARTITION BY registro_ans ORDER BY (o.situacao = 'ativa') DESC) AS rn
    FROM operadoras o
    JOIN ultimo u USING (situacao, snapshot)
)
SELECT
    registro_ans,
    cnpj,
    razao_social,
    coalesce(nome_fantasia, razao_social) AS nome,
    modalidade,
    logradouro,
    numero,
    complemento,
    bairro,
    cidade,
    uf AS uf_sede,
    cep,
    ddd,
    telefone,
    email,
    regiao_comercializacao,
    data_registro_ans,
    situacao,
    data_descredenciamento,
    motivo_descredenciamento
FROM cadastro
WHERE rn = 1

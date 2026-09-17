-- Dimensão de operadoras: último snapshot de ativas + canceladas (ativa tem prioridade).
-- Usa janela em vez de JOIN com as colunas de partição: no DuckDB 1.5.5 o JOIN
-- (situacao, snapshot) gerava linhas duplicadas e descartava as canceladas ao materializar.
WITH com_ultimo AS (
    SELECT *, max(snapshot) OVER (PARTITION BY situacao) AS ultimo_snapshot
    FROM operadoras
),
cadastro AS (
    SELECT *,
           row_number() OVER (PARTITION BY registro_ans ORDER BY (situacao = 'ativa') DESC) AS rn
    FROM com_ultimo
    WHERE snapshot = ultimo_snapshot
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

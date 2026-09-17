-- Consultas de exemplo sobre data/ans_bi.duckdb (gere com `make banco`).
-- No SQLTools: conexão "ANS BI (DuckDB)", selecione uma consulta e rode (Ctrl+E Ctrl+E).
--
-- Organização:
--   gold.*    tabelas prontas para análise (o que o painel usa)
--   silver.*  dados tratados, linha a linha, como vieram da ANS
-- Chave de integração entre todas as tabelas: registro_ans

-- 1. As 20 maiores operadoras ativas e seus indicadores
SELECT nome, uf_sede, beneficiarios, round(idss * 10, 1) AS nota_qualidade_0a10, igr, pct_resolvidas
FROM gold.painel_operadora
WHERE situacao = 'ativa'
ORDER BY beneficiarios DESC
LIMIT 20;

-- 2. Operadoras com sede em um estado (troque 'RS')
SELECT p.nome, d.cidade, p.beneficiarios, round(p.idss * 10, 1) AS nota_qualidade_0a10, p.igr
FROM gold.painel_operadora p
JOIN gold.dim_operadora d USING (registro_ans)
WHERE d.uf_sede = 'RS' AND p.situacao = 'ativa' AND p.beneficiarios > 0
ORDER BY p.beneficiarios DESC;

-- 3. Evolução de clientes de uma operadora (troque o registro)
SELECT competencia, sum(beneficiarios) AS clientes
FROM gold.beneficiarios_mensal
WHERE registro_ans = '352501'
GROUP BY competencia
ORDER BY competencia;

-- 4. Crescimento de clientes por ano (fim de ano contra fim do ano anterior)
WITH fim_de_ano AS (
    SELECT registro_ans, year(competencia) AS ano,
           arg_max(beneficiarios, competencia) AS clientes
    FROM (SELECT registro_ans, competencia, sum(beneficiarios) AS beneficiarios
          FROM gold.beneficiarios_mensal GROUP BY ALL)
    GROUP BY ALL
)
SELECT ano, clientes,
       round(100.0 * (clientes / lag(clientes) OVER (ORDER BY ano) - 1), 1) AS crescimento_pct
FROM fim_de_ano
WHERE registro_ans = '352501'
ORDER BY ano;

-- 5. Assuntos mais reclamados no Brasil nos últimos 12 meses
SELECT assunto, sum(demandas) AS reclamacoes
FROM gold.nip_mensal
WHERE competencia > (SELECT max(competencia) FROM gold.beneficiarios_mensal) - INTERVAL 12 MONTH
GROUP BY assunto
ORDER BY reclamacoes DESC
LIMIT 10;

-- 6. Transferências de carteira (saltos de mais de 30% num mês)
WITH mensal AS (
    SELECT registro_ans, competencia, sum(beneficiarios) AS v
    FROM gold.beneficiarios_mensal GROUP BY ALL
),
dif AS (
    SELECT *, v - lag(v) OVER (PARTITION BY registro_ans ORDER BY competencia) AS variacao FROM mensal
)
SELECT d.nome, competencia, variacao
FROM dif JOIN gold.dim_operadora d USING (registro_ans)
WHERE abs(variacao) >= 5000 AND abs(variacao) >= 0.3 * v
ORDER BY abs(variacao) DESC;

-- 7. Dicionário: tabelas e descrições
SELECT schema_name AS esquema, view_name AS tabela, comment AS descricao
FROM duckdb_views() WHERE NOT internal ORDER BY 1, 2;

-- 8. TISS (internações): NÃO tem registro_ans — a ANS publica esse dado anonimizado.
--    A única ligação possível é por GRUPO (uf + modalidade + porte), e mesmo assim é aproximada:
--    a UF do TISS é a do hospital que atendeu, não a da sede da operadora.
--    Serve como contexto de mercado; não dá para dizer quantas internações são de uma operadora.
WITH grupos AS (
    SELECT uf_sede AS uf, lower(modalidade) AS modalidade, upper(strip_accents(porte)) AS porte,
           count(*) AS operadoras, list(nome ORDER BY beneficiarios DESC)[1:3] AS maiores
    FROM gold.painel_operadora
    WHERE situacao = 'ativa' AND beneficiarios > 0
    GROUP BY ALL
)
SELECT t.competencia, t.uf, t.modalidade, t.porte, t.internacoes, g.operadoras, g.maiores
FROM gold.tiss_internacoes_mensal t
JOIN grupos g ON g.uf = t.uf
             AND g.modalidade = lower(t.modalidade)
             AND g.porte = upper(strip_accents(t.porte))  -- 'Médio' -> 'MEDIO'
WHERE t.competencia = DATE '2024-01-01' AND t.uf = 'RS'
ORDER BY t.internacoes DESC;

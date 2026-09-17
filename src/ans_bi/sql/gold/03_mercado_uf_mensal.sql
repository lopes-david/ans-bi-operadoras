-- Visão de mercado por UF: total de vidas e número de operadoras com carteira.
SELECT
    competencia,
    uf,
    cobertura,
    sum(beneficiarios)::BIGINT                                 AS beneficiarios,
    count(DISTINCT registro_ans) FILTER (WHERE beneficiarios > 0) AS operadoras
FROM beneficiarios_mensal
GROUP BY ALL

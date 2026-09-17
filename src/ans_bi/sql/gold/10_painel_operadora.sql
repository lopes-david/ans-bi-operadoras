-- Uma linha por operadora com os indicadores-chave (base do ranking do dashboard).
WITH ref AS (
    SELECT max(competencia) AS c FROM beneficiarios_mensal
),
ben AS (
    SELECT
        registro_ans,
        sum(beneficiarios) FILTER (WHERE competencia = ref.c)                                   AS beneficiarios,
        sum(beneficiarios) FILTER (WHERE competencia = ref.c - INTERVAL 12 MONTH)               AS beneficiarios_12m_antes,
        sum(beneficiarios) FILTER (WHERE competencia = ref.c AND cobertura = 'Médico-hospitalar') AS beneficiarios_medico,
        sum(beneficiarios) FILTER (WHERE competencia = ref.c AND cobertura = 'Odontológico')     AS beneficiarios_odonto,
        count(DISTINCT uf) FILTER (WHERE competencia = ref.c)                                   AS ufs_atuacao,
        arg_max(uf, beneficiarios) FILTER (WHERE competencia = ref.c)                           AS uf_principal
    FROM beneficiarios_mensal, ref
    GROUP BY registro_ans
),
nip12 AS (
    SELECT registro_ans, sum(demandas) AS nip_12m
    FROM nip_mensal, ref
    WHERE competencia > ref.c - INTERVAL 12 MONTH AND competencia <= ref.c
    GROUP BY registro_ans
),
igr_atual AS (
    -- prioriza o IGR de assistência médica; operadoras só odontológicas usam o delas
    SELECT registro_ans,
           arg_max(igr, (competencia, cobertura = 'Assistência médica'))   AS igr,
           arg_max(cobertura, (competencia, cobertura = 'Assistência médica')) AS igr_cobertura,
           max(competencia)                                                AS igr_competencia
    FROM igr_mensal
    GROUP BY registro_ans
),
-- reclamações resolvidas na mediação da ANS (NIP classificada como INATIVA ou RVE) sobre as encerradas
-- com resultado (inclui NÚCLEO, que virou processo); em andamento, não procedentes e fora de competência ficam fora
resolucao AS (
    SELECT registro_ans,
           count(*) FILTER (WHERE classificacao_nip IN ('INATIVA', 'RVE'))           AS nip_resolvidas_12m,
           count(*) FILTER (WHERE classificacao_nip IN ('INATIVA', 'RVE', 'NÚCLEO')) AS nip_avaliadas_12m
    FROM nip, ref
    WHERE competencia > ref.c - INTERVAL 12 MONTH AND competencia <= ref.c
    GROUP BY registro_ans
),
idss_atual AS (
    SELECT registro_ans, arg_max(valor, ano_avaliacao) AS idss, max(ano_avaliacao) AS idss_ano
    FROM idss_indicadores
    WHERE indicador = 'IDSS'
    GROUP BY registro_ans
)
SELECT
    coalesce(d.registro_ans, b.registro_ans)                AS registro_ans,
    coalesce(d.nome, 'Operadora ' || b.registro_ans)        AS nome,
    d.razao_social,
    d.modalidade,
    d.uf_sede,
    coalesce(d.situacao, 'desconhecida')                    AS situacao,
    (SELECT c FROM ref)                                     AS competencia_ref,
    coalesce(b.beneficiarios, 0)                            AS beneficiarios,
    b.beneficiarios_medico,
    b.beneficiarios_odonto,
    b.beneficiarios_12m_antes,
    round(100.0 * (b.beneficiarios - b.beneficiarios_12m_antes) / nullif(b.beneficiarios_12m_antes, 0), 2)
                                                            AS variacao_12m_pct,
    b.ufs_atuacao,
    b.uf_principal,
    coalesce(n.nip_12m, 0)                                  AS nip_12m,
    round(100000.0 * n.nip_12m / nullif(b.beneficiarios, 0), 2) AS nip_por_100mil,
    i.igr,
    i.igr_cobertura,
    -- critério de porte da ANS: pequeno < 20 mil, médio < 100 mil, grande >= 100 mil beneficiários
    CASE
        WHEN coalesce(b.beneficiarios, 0) >= 100000 THEN 'Grande'
        WHEN coalesce(b.beneficiarios, 0) >= 20000 THEN 'Médio'
        ELSE 'Pequeno'
    END                                                     AS porte,
    i.igr_competencia,
    s.idss,
    s.idss_ano,
    coalesce(r.nip_resolvidas_12m, 0)                        AS nip_resolvidas_12m,
    coalesce(r.nip_avaliadas_12m, 0)                         AS nip_avaliadas_12m,
    round(100.0 * r.nip_resolvidas_12m / nullif(r.nip_avaliadas_12m, 0), 1) AS pct_resolvidas
FROM dim_operadora d
FULL JOIN ben b USING (registro_ans)
LEFT JOIN nip12 n ON n.registro_ans = coalesce(d.registro_ans, b.registro_ans)
LEFT JOIN igr_atual i ON i.registro_ans = coalesce(d.registro_ans, b.registro_ans)
LEFT JOIN idss_atual s ON s.registro_ans = coalesce(d.registro_ans, b.registro_ans)
LEFT JOIN resolucao r ON r.registro_ans = coalesce(d.registro_ans, b.registro_ans)
WHERE d.situacao = 'ativa' OR coalesce(b.beneficiarios, 0) > 0

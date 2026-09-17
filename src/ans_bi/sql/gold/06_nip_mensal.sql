-- Reclamações (NIP) por operadora x UF do beneficiário x natureza x grupo de assunto.
SELECT
    competencia,
    registro_ans,
    coalesce(nullif(trim(uf_beneficiario), ''), 'NI') AS uf,
    coalesce(nullif(natureza_nip, ''), 'Não classificada') AS natureza,
    coalesce(nullif(assunto_grupo, ''), 'Não informado') AS assunto_grupo,
    -- último nível do caminho "Produto ou Plano >> Cobertura >> Rol de Procedimentos..."
    coalesce(nullif(trim(regexp_extract(assunto, '([^>]+)$', 1)), ''), 'Não informado') AS assunto,
    count(*)::INTEGER AS demandas
FROM nip
WHERE competencia IS NOT NULL
GROUP BY ALL

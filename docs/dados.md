# Dados

Todas as bases vêm de `https://dadosabertos.ans.gov.br/FTP/PDA/`: CSV separado por `;`, às vezes
dentro de ZIP. A codificação é detectada arquivo a arquivo, porque a ANS já publicou em latin-1 e
hoje publica em UTF-8. Todas as colunas são lidas como texto e convertidas explicitamente nos SQLs
(`TRY_CAST`), para que uma linha malformada vire `NULL` em vez de derrubar a carga.

A chave de integração é o **registro ANS da operadora** (6 dígitos, com zeros à esquerda).

## Fontes

### Cadastro de operadoras
- Arquivos: `operadoras_de_plano_de_saude_ativas/Relatorio_cadop.csv` e `..._canceladas/Relatorio_cadop_canceladas.csv`.
- A ANS publica só a "foto" atual. O pipeline guarda **um snapshot por dia**
  (`silver/operadoras/situacao=.../snapshot=YYYY-MM-DD`), o que cria o histórico que a fonte não tem.
- Dados de contato e representantes são descartados: não são necessários para o BI.

### Beneficiários: Informações Consolidadas de Beneficiários (ICB)
- Arquivos: `informacoes_consolidadas_de_beneficiarios-024/AAAAMM/pda-024-icb-UF-AAAA_MM.zip` (um por UF; `XX` = UF não informada).
- O arquivo original tem uma linha por plano × município × sexo × faixa etária. O pipeline gera duas tabelas sem o código do plano:
  - `beneficiarios_municipio`: operadora × município × tipo de contratação × cobertura;
  - `beneficiarios_perfil`: operadora × UF × sexo × faixa etária × cobertura × tipo de vínculo.
- `QT_BENEFICIARIO_ATIVO` conta **vínculos** (uma pessoa com dois planos conta duas vezes), o que é o padrão da ANS.
- O SIB microdado (`dados_de_beneficiarios_por_operadora`) não é usado: é muito maior e não acrescenta nada aos indicadores por operadora.

### Reclamações: NIP
- Arquivos: `demandas_dos_consumidores_nip/pda-013-demandas_dos_consumidores_nip-AAAA.csv`.
- Uma linha por demanda. A competência vem de `ANO_DE_REFERENCIA`/`MES_DE_REFERENCIA`.
- O assunto é um caminho (`Produto ou Plano >> Cobertura >> Rol de Procedimentos...`):
  - `assunto_grupo` guarda o 2º nível;
  - o mart `nip_mensal` usa o último nível.

### IGR: Índice Geral de Reclamações (versão 2023)
- Arquivo: `IGR/IGR_versao_2023/pda-023-igr.csv` (mensal, desde 2015).
- Há uma linha por operadora × cobertura (assistência médica / exclusivamente odontológica).
- O painel usa a de assistência médica quando ela existe.

### IDSS
- Arquivos: `historico_idss-020/pda-020-historico-idss-*.csv`.
- O formato original é largo (`IDSS_2025_2024` = avaliação 2025, ano-base 2024). O pipeline converte para formato longo e descarta `ND`.

### TISS hospitalar (opcional)
- Arquivos: `TISS/HOSPITALAR/AAAA/UF/UF_AAAAMM_HOSP_CONS.zip`.
- **Não identifica a operadora** (traz só um ID de plano anonimizado). Por isso a agregação é por UF/município do prestador, modalidade e porte.
- A publicação tem defasagem de vários meses.

## Limitações conhecidas

- A ANS revisa arquivos já publicados. O planner detecta a mudança (data/tamanho no índice) e
  reprocessa a partição.
- A execução diária revisita só os últimos `ANS_LOOKBACK_MONTHS` meses (padrão 3) do ICB e os
  2 últimos anos do TISS. Revisões mais antigas exigem `backfill`.
- "Reclamações por 100 mil beneficiários" no painel é uma taxa simples: NIP de 12 meses dividida
  pela carteira atual do recorte. Não é o IGR oficial, que tem metodologia própria.
- Variações muito grandes de carteira (ex.: +8.000%) normalmente são transferências de carteira ou
  mudanças de registro entre operadoras do mesmo grupo, e não erro de carga.

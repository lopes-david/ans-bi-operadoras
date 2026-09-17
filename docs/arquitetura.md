# Arquitetura e decisões

Este documento registra as escolhas feitas em relação à proposta original
(Lambda → S3 → Athena → QuickSight) e o motivo de cada uma. O critério foi sempre o mesmo:
**menor custo operacional, sem perder desempenho, e reprodutível por qualquer pessoa**.

## O que foi mantido da proposta

| Proposta | Implementação |
|---|---|
| Extração com AWS Lambda | Lambda Python 3.12 em **ARM64** (Graviton, ~20% mais barata) |
| Agendamento com EventBridge | **EventBridge Scheduler**, 1 execução diária com fuso de São Paulo |
| Data lake no S3 em Parquet | S3 com camadas `silver/` e `gold/`, Parquet com compressão zstd |
| SQL com Athena | Athena com tabelas registradas via API e *partition projection* |
| Budgets e Free Tier | Orçamento mensal com alertas por e-mail (`make deploy ALERT_EMAIL=...`) |

## O que mudou, e por quê

### QuickSight → painel Streamlit

QuickSight cobra por usuário/mês, e para um BI **público** isso cresce com a audiência.
No lugar dele, o painel é um app Streamlit (Python):
- é a mesma linguagem do pipeline, então o foco do projeto continua nos dados;
- já vem com busca, filtros, tabelas ordenáveis e exportação CSV, sem escrever front-end;
- carrega os marts (~6 MB) num DuckDB em memória, então cada filtro responde em milissegundos;
- roda num container (`docker compose`) em qualquer servidor, ou de graça no Streamlit Community Cloud;
- não exige login: é um BI público, como o projeto pede.

Alternativas avaliadas:
- Um site estático com DuckDB-WASM: custo zero, mas exigia muito código de interface.
- Evidence.dev: passou a depender de uma nuvem proprietária.
- Metabase: servidor pesado, com custo fixo.

O Athena continua disponível para análises ad hoc em SQL. O QuickSight pode ser ligado às
mesmas tabelas do Glue, se algum dia fizer sentido.

### Uma Lambda "faz-tudo" → planner + fila SQS + worker

Um arquivo por invocação isola falhas: um arquivo que falha é reprocessado sozinho e, após três
tentativas, vai para a DLQ. Isso também mantém cada execução bem abaixo do limite de 15 minutos. A
concorrência fica limitada em 3 (`workerConcurrency`), porque contas novas têm limite total de 10
execuções simultâneas.

### "Fargate/EC2 para bases grandes" → desnecessário

A proposta previa Fargate/EC2 para a base de beneficiários. Duas decisões eliminaram essa necessidade:

1. Usar a base **ICB** (`informacoes_consolidadas_de_beneficiarios-024`), que já vem agregada,
   em vez do microdado do SIB (`dados_de_beneficiarios_por_operadora`, com SP = 3 GB zipado).
2. Agregar já na entrada, sem o código do plano. O maior arquivo (SP, ~2,5 GB de CSV) é processado
   em ~20 s com ~430 MB de RAM. A Lambda tem 2 GB de memória e 6 GB de disco temporário.

### Glue Crawler → registro direto via API

Crawlers custam por DPU-hora. O worker lê o esquema dos próprios Parquet (DuckDB) e cria ou atualiza
as tabelas no Glue Data Catalog. As partições usam *partition projection*, então não é preciso rodar
`MSCK REPAIR` nem crawler.

### DuckDB em vez de Pandas/Spark (ou ClickHouse)

- DuckDB lê CSV grande em streaming, com memória limitada e spill em disco.
- Escreve Parquet direto.
- Roda embutido na Lambda e também no navegador (WASM), então o mesmo SQL serve aos dois lados.
- ClickHouse exigiria um servidor sempre ligado.
- Spark/Glue Jobs custam por DPU-hora.

### Backfill local opcional

O histórico pode ser processado na máquina de quem mantém o projeto (`make backfill`) e enviado com
`make seed`. Upload para o S3 não tem custo de transferência. Processar na nuvem (`make invoke-backfill`)
também cabe na camada gratuita da Lambda, mas o caminho local é útil para desenvolver.

## Camadas

```
s3://<bucket>/
  silver/            1 partição por arquivo da ANS (substituída quando a ANS republica)
  gold/<mart>/       marts com nome estável (tabelas do Athena)
  site/data/         marts públicos com nome imutável (<mart>.<hash>.parquet) + manifest.json
  state/done/        marcadores de versão processada (planner compara com o índice da ANS)
  state/gold.json    impressão digital da silver usada na última gold
  athena-results/    resultados de consultas (expiram em 7 dias)
```

O bucket é privado. O CloudFront acessa apenas `site/` via Origin Access Control.

### Marts da gold

| Mart | Uso |
|---|---|
| `dim_operadora` | cadastro mais recente (ativas + canceladas) |
| `beneficiarios_mensal` | vidas por competência × operadora × UF × cobertura × contratação |
| `mercado_uf_mensal` | total de vidas e de operadoras por UF |
| `beneficiarios_municipio_atual` | distribuição por município na última competência |
| `perfil_etario` | sexo × faixa etária na última competência |
| `nip_mensal` | reclamações por competência × operadora × UF × natureza × assunto |
| `igr_mensal` | IGR por operadora e cobertura |
| `idss_indicadores` | IDSS e dimensões (IDQS, IDGA, IDSM, IDGR) por ano |
| `tiss_internacoes_mensal` | internações por UF do prestador, modalidade e porte |
| `painel_operadora` | uma linha por operadora com os indicadores-chave |

## Custos

Estimativa para `sa-east-1` com o histórico desde 2021 e o agendamento diário. Os preços variam;
confira sempre a calculadora da AWS.

| Serviço | Uso mensal típico | Custo |
|---|---|---|
| Lambda (ARM) | ~150 invocações do worker × 2 GB × ~20 s ≈ 6 mil GB-s | dentro dos 400 mil GB-s gratuitos |
| SQS | algumas centenas de mensagens | dentro de 1 milhão gratuito |
| EventBridge Scheduler | 30 execuções | dentro de 14 milhões gratuitos |
| S3 | < 1 GB armazenado, alguns milhares de requisições | poucos centavos de dólar |
| CloudFront | download público dos marts | dentro de 1 TB / 10 milhões de requisições gratuitos |
| Glue Data Catalog | ~20 tabelas | dentro de 1 milhão de objetos gratuitos |
| Athena | consultas sobre a gold (KB a MB) | centavos; limite de 1 GB por consulta |
| CloudWatch Logs | retenção de 14 dias | dentro dos 5 GB gratuitos |
| **Total** | | **≈ US$ 0 a 1 por mês** |

O backfill completo na nuvem (~3,5 mil arquivos) consome ~150 mil GB-s, ainda dentro da cota
gratuita mensal da Lambda.

O que **não** existe na stack, de propósito, porque cobra por hora: VPC com NAT Gateway, RDS/Redshift,
instâncias EC2/Fargate, Glue Crawlers/Jobs e QuickSight.

### Proteções de custo

- Orçamento mensal (padrão US$ 5) com alertas em 50%, 100% e previsão de 100%.
- Workgroup do Athena com corte em 1 GB escaneado por consulta.
- Concorrência máxima do worker e DLQ, para que um erro não vire um loop de reprocessamento.
- Lifecycle: uploads incompletos são abortados em 1 dia e resultados do Athena expiram em 7 dias.
- Logs com retenção de 14 dias.

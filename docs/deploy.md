# Deploy na AWS

A infraestrutura é definida com AWS CDK (Python) em [`infra/`](../infra). Nenhum nome de conta,
bucket ou domínio fica fixo no código: tudo é gerado na sua conta.

## 1. Credenciais (não use a conta root)

Chaves de acesso da conta root dão poder total e não podem ser restringidas. Crie uma identidade própria:

1. No console, abra **IAM Identity Center** (recomendado) ou **IAM → Usuários** e crie um usuário para você.
2. Para a **primeira vez** (`make bootstrap`), use uma identidade com `AdministratorAccess`,
   porque o bootstrap cria as funções IAM que o CDK usa.
3. No dia a dia, basta a política [`iam-operador.json`](iam-operador.json):
   - ela só permite assumir as funções do CDK criadas no bootstrap e operar o pipeline;
   - no recurso `SeedLake`, troque `ansbi-lake*` pelo nome do bucket mostrado em `make outputs`.
4. Configure um perfil local e aponte o `.env` para ele:

```bash
aws configure --profile ans-bi        # ou: aws configure sso
echo "AWS_PROFILE=ans-bi" >> .env
```

Se chaves da conta root já foram criadas, **desative-as e apague-as** em
*IAM → Credenciais de segurança* depois de configurar a nova identidade.

## 2. Pré-requisitos

- [uv](https://docs.astral.sh/uv/) e Python 3.12+;
- Node.js 20+ (o CLI do CDK roda via `npx`);
- AWS CLI v2;
- `curl`.

## 3. Publicar

```bash
make setup
make bootstrap                        # uma vez por conta/região
make deploy ALERT_EMAIL=voce@exemplo.com
make outputs
```

O `deploy`:
1. empacota a Lambda para ARM64 (DuckDB + extensão `httpfs` embutida, ~70 MB);
2. mostra as mudanças de permissões e pede confirmação;
3. cria os recursos.

O e-mail recebe uma confirmação da AWS Budgets.

Parâmetros ajustáveis em [`infra/cdk.json`](../infra/cdk.json) ou com `-c chave=valor`:

| Chave | Padrão | Descrição |
|---|---|---|
| `stackName` | `AnsBi` | nome da stack |
| `scheduleCron` / `scheduleTimezone` | `cron(0 8 * * ? *)` / `America/Sao_Paulo` | horário da verificação diária |
| `workerConcurrency` | `3` | workers em paralelo (contas novas têm limite total de 10) |
| `workerMemoryMb` | `2048` | memória do worker |
| `startYear` | `2021` | início do histórico |
| `budgetUsd` / `alertEmail` | `5` / vazio | orçamento mensal; sem e-mail, o orçamento não é criado |
| `retainData` | `true` | mantém o bucket se a stack for removida |

## 4. Carga inicial

Escolha um caminho:

```bash
# A) processar na nuvem (~3,5 mil arquivos; acompanhe com make logs)
make invoke-backfill

# B) processar localmente e enviar (útil se você já rodou make backfill)
make seed
```

Quando a fila esvazia, o worker monta a gold sozinho. Para forçar, use `make invoke-gold`.
Os marts ficam públicos na URL `PublicDataUrl` mostrada por `make outputs`. Para o painel ler
de lá, rode-o com `ANS_GOLD_URI=<PublicDataUrl>`, seja no servidor próprio ou no
[Streamlit Community Cloud](https://streamlit.io/cloud), que é gratuito para repositórios públicos
(arquivo principal `app/streamlit_app.py`; defina `ANS_GOLD_URI` nos *secrets* como variável de ambiente).

## 5. Operação

| Comando | Para quê |
|---|---|
| `make invoke-planner` | verificar a ANS agora, sem esperar o agendamento |
| `make logs` | acompanhar o worker |
| `make dlq` | ver quantos arquivos falharam três vezes (inspecione a DLQ no console e reenvie) |
| `make diff` / `make deploy` | aplicar mudanças de código ou infraestrutura |
| `make destroy` | remover a stack (o bucket fica se `retainData=true`) |

## Consultas no Athena

No console do Athena, selecione o workgroup **ans-bi** e o database **ans_bi**:

```sql
SELECT nome, beneficiarios, nip_por_100mil, igr, idss
FROM painel_operadora
ORDER BY beneficiarios DESC
LIMIT 20;

-- silver particionada: sempre filtre pela partição para escanear pouco
SELECT uf, sum(qt_ativos) AS vidas
FROM silver_beneficiarios_municipio
WHERE competencia = '2026-07'
GROUP BY uf ORDER BY vidas DESC;
```

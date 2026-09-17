# ANS BI Operadoras

Baixa os [dados abertos da ANS](https://dadosabertos.ans.gov.br/FTP/PDA/) sobre planos de saúde,
organiza tudo em tabelas prontas para análise e mostra num painel.

Roda no seu computador: **sem servidor, sem banco de dados para instalar e sem conta em nuvem.**

> Este repositório tem só o código. **Os dados não vêm aqui dentro** — você baixa direto da ANS
> com um comando, e eles ficam na sua máquina (`data/`, fora do git).

## Começando

Requisitos: [uv](https://docs.astral.sh/uv/) e Python 3.12+.

```bash
make setup                      # instala as dependências
ANS_UFS=SP,RJ make run          # baixa da ANS e monta as tabelas (alguns minutos)
make app                        # painel em http://localhost:8501
```

- `make run` sem `ANS_UFS` baixa **todas** as UFs; rodando de novo, só o que a ANS mudou desde a última vez.
- `make backfill` baixa todo o histórico desde 2021 (~10 GB, de 20 a 30 minutos numa conexão boa).
- `make help` lista todos os comandos.
- Prefere container? `docker compose up -d --build` sobe o painel e a atualização diária.

## Consultar os dados em SQL

```bash
make banco
```

Isso gera **`data/ans_bi.duckdb`**: um arquivo pequeno (centenas de KB) que não copia nada — são só
views sobre os dados baixados, já com descrição de cada tabela e coluna. Abra com qualquer ferramenta
que fale DuckDB (CLI do DuckDB, DBeaver, ou a extensão SQLTools no VS Code):

```sql
SELECT nome, uf_sede, beneficiarios, round(idss * 10, 1) AS nota, igr
FROM gold.painel_operadora
WHERE situacao = 'ativa'
ORDER BY beneficiarios DESC
LIMIT 10;
```

Mais exemplos prontos em [sql/exemplos/consultas.sql](sql/exemplos/consultas.sql).
Gere o arquivo de novo (`make banco`) depois de cada atualização dos dados.

<details>
<summary>Conectar pelo VS Code (SQLTools)</summary>

Instale a extensão **SQLTools** e o driver `Evidence.sqltools-duckdb-driver`, e crie um
`.vscode/settings.json` com o caminho da sua cópia do projeto (essa pasta não vai para o git):

```json
{
  "sqltools.connections": [
    {
      "name": "ANS BI (DuckDB)",
      "driver": "DuckDB",
      "databaseFilePath": "/caminho/para/ans-bi-operadoras/data/ans_bi.duckdb",
      "accessMode": "Read Only",
      "previewLimit": 100
    }
  ],
  "sqltools.useNodeRuntime": true
}
```

Feche a conexão antes de rodar `make banco` de novo, senão o arquivo fica travado.
</details>

### As tabelas

O esquema **`gold`** é o que você vai usar quase sempre: uma tabela por assunto, já limpa e agregada.
A chave que liga todas elas é o **`registro_ans`** (o código da operadora na ANS).

| Tabela | O que tem |
|---|---|
| `painel_operadora` | **comece por aqui**: uma linha por operadora, com clientes, reclamações, IGR e IDSS |
| `dim_operadora` | cadastro: nome, CNPJ, endereço, telefone, situação (ativa ou cancelada) |
| `beneficiarios_mensal` | clientes por mês, operadora, UF, cobertura e tipo de contratação |
| `nip_mensal` | reclamações por mês, operadora, UF e assunto |
| `igr_mensal` | Índice Geral de Reclamações (reclamações por 100 mil clientes) por mês |
| `idss_indicadores` | nota de qualidade IDSS e suas quatro dimensões, por ano |
| `mercado_uf_mensal` | total de clientes e de operadoras por estado |
| `beneficiarios_municipio_atual`, `perfil_etario` | recortes por município e por sexo/faixa etária |
| `tiss_internacoes_mensal` | internações por estado, modalidade e porte (sem identificar a operadora) |

O esquema **`silver`** guarda os mesmos dados linha a linha, como a ANS publica, caso você queira
fazer suas próprias agregações.

## O painel

```bash
make app
```

A tela inicial é um **mapa do Brasil**. Clicando num estado, aparecem as operadoras **com sede** ali
e o total de clientes de cada uma no país. O estado escolhido fica na URL (`/?uf=RS`), então o link
pode ser compartilhado.

Clicar numa operadora abre a ficha, escrita para quem não é da área, em três abas: **Resumo**
(clientes, qualidade e reclamações com leitura em palavras e semáforo 🟢🟡🔴, assuntos mais reclamados),
**Histórico** (clientes e reclamações por trimestre, nota por ano) e **Contato**.

O mapa é um componente próprio em SVG (`app/componentes/`), feito a partir da malha oficial do IBGE,
sem bibliotecas externas.

## De onde vêm os dados

Tudo vem do portal de dados abertos da ANS, em CSV (às vezes dentro de ZIP):

| Fonte | O que traz |
|---|---|
| Cadastro de operadoras | nome, CNPJ, endereço e situação de cada operadora |
| Beneficiários consolidados (ICB) | quantos clientes cada operadora tem, por mês e município |
| Reclamações (NIP) | uma linha por reclamação de consumidor |
| IGR | índice de reclamações por 100 mil clientes |
| IDSS | nota de qualidade da ANS, por ano |
| TISS hospitalar | internações consolidadas (anônimas) |

Cada arquivo baixado vira um Parquet em `data/lake/silver/`, e os SQLs em
[`src/ans_bi/sql/`](src/ans_bi/sql) montam as tabelas da `gold`. Detalhes, decisões e limitações de
cada base: [docs/dados.md](docs/dados.md).

## Rodar na nuvem (opcional)

O mesmo código roda em AWS Lambda, gravando no S3 e atualizando sozinho todo dia, dentro da camada
gratuita (≈ US$ 0 a 1 por mês). É opcional: nada aqui exige conta na AWS.
Passo a passo: [docs/deploy.md](docs/deploy.md) · Arquitetura e custos: [docs/arquitetura.md](docs/arquitetura.md).

## Estrutura

```
src/ans_bi/          pipeline: baixa da ANS, converte e monta as tabelas
  sources.py           catálogo de fontes da ANS
  pipeline.py          o que mudou e o que processar
  gold.py              tabelas prontas para análise
  banco.py             gera o data/ans_bi.duckdb (make banco)
  sql/silver, sql/gold
app/                 painel Streamlit
sql/exemplos/        consultas SQL de exemplo
docs/                dados, arquitetura e deploy
infra/               infraestrutura AWS (CDK, opcional)
tests/               testes, sem rede
```

## Desenvolvimento

```bash
make test lint
```

Contribuições são bem-vindas. Para acrescentar uma fonte da ANS: uma entrada em `sources.py`,
um SQL em `sql/silver` e, se for aparecer no painel, um mart em `sql/gold`.

## Licença

[MIT](LICENSE). Os dados são da ANS e seguem os termos do Portal Brasileiro de Dados Abertos.
Este projeto não tem vínculo com a ANS.

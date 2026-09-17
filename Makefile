# Atalhos do projeto. Variáveis do .env (se existir) são exportadas para os comandos.
-include .env
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env 2>/dev/null)

STACK        ?= AnsBi
REGION       ?= $(or $(AWS_DEFAULT_REGION),sa-east-1)
CDK          := cd infra && JSII_SILENCE_WARNING_DEPRECATED_NODE_VERSION=1 npx --yes aws-cdk@2
# saída da stack, resolvida pelo shell da receita: $(call output,BucketName)
output        = $$(aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
                  --query "Stacks[0].Outputs[?OutputKey=='$(1)'].OutputValue" --output text)

.PHONY: help setup lint fmt test run backfill gold app docker-up docker-down build synth bootstrap deploy diff destroy \
        seed invoke-planner invoke-backfill invoke-gold logs dlq outputs clean

help: ## lista os comandos
	@grep -hE '^[a-z-]+:.*## ' $(firstword $(MAKEFILE_LIST)) | awk -F':.*## ' '{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

# --- desenvolvimento local (não precisa de AWS) ------------------------------------------
setup: ## instala dependências (Python via uv)
	uv sync --all-groups

lint: ## verifica estilo
	uv run ruff check . && uv run ruff format --check .

fmt: ## formata o código
	uv run ruff format . && uv run ruff check --fix .

test: ## roda os testes
	uv run pytest -q

run: ## processa localmente o que mudou na ANS (últimos meses) e monta a gold
	uv run ans-bi run -j 4

backfill: ## processa localmente todo o histórico desde ANS_START_YEAR (demorado, ~10 GB de download)
	uv run ans-bi run --backfill -j 4

gold: ## reconstrói a camada gold
	uv run ans-bi gold --force

app: ## abre o painel em http://localhost:8501 usando o lake local
	uv run --group app streamlit run app/streamlit_app.py

docker-up: ## sobe painel + pipeline diário em containers (servidor próprio)
	docker compose up -d --build

docker-down: ## para os containers
	docker compose down

# --- AWS ---------------------------------------------------------------------------------
build: ## empacota o código da Lambda (ARM64)
	./scripts/build_lambda.sh

synth: build ## gera o template CloudFormation sem publicar nada
	$(CDK) synth -q

bootstrap: ## prepara a conta/região para o CDK (uma vez por conta)
	$(CDK) bootstrap

diff: build ## mostra o que o deploy vai mudar
	$(CDK) diff

deploy: build ## publica a stack (use ALERT_EMAIL=voce@exemplo.com para o alerta de custo)
	$(CDK) deploy --require-approval broadening $(if $(ALERT_EMAIL),-c alertEmail=$(ALERT_EMAIL))

destroy: ## remove a stack (o bucket é mantido se retainData=true)
	$(CDK) destroy

outputs: ## mostra URL dos dados públicos, bucket etc.
	@aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table

seed: ## envia o lake local (silver + controle) para o S3 e monta a gold na nuvem
	aws s3 sync data/lake/silver s3://$(call output,BucketName)/silver --region $(REGION) --size-only
	aws s3 sync data/lake/state/done s3://$(call output,BucketName)/state/done --region $(REGION) --size-only
	$(MAKE) invoke-gold

invoke-planner: ## dispara a verificação diária agora
	aws lambda invoke --region $(REGION) --function-name $(call output,PlannerFunction) \
	  --cli-binary-format raw-in-base64-out --payload '{}' /dev/stdout

invoke-backfill: ## enfileira todo o histórico para processamento na nuvem
	aws lambda invoke --region $(REGION) --function-name $(call output,PlannerFunction) \
	  --cli-binary-format raw-in-base64-out --payload '{"backfill": true}' /dev/stdout

invoke-gold: ## reconstrói a gold na nuvem
	aws lambda invoke --region $(REGION) --function-name $(call output,WorkerFunction) \
	  --cli-binary-format raw-in-base64-out --payload '{"type": "gold", "force": true}' \
	  --cli-read-timeout 900 /dev/stdout

logs: ## acompanha os logs do worker
	aws logs tail --region $(REGION) --follow /aws/lambda/$(call output,WorkerFunction)

dlq: ## quantas mensagens falharam definitivamente
	aws sqs get-queue-attributes --region $(REGION) --queue-url $(call output,DeadLetterQueueUrl) \
	  --attribute-names ApproximateNumberOfMessages --output text

clean: ## apaga artefatos de build (não apaga dados)
	rm -rf build infra/cdk.out .pytest_cache .ruff_cache

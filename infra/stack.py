"""Infraestrutura de custo mínimo.

Nada fica ligado: Lambdas sob demanda, fila SQS, S3 e CloudFront (camada gratuita cobre o uso
típico). Não há NAT, VPC, banco de dados, Glue Crawler nem QuickSight. O painel (Streamlit)
roda fora da AWS: no servidor próprio (docker compose) ou no Streamlit Community Cloud.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_athena as athena,
    aws_budgets as budgets,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_glue as glue,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as sources,
    aws_logs as logs,
    aws_s3 as s3,
    aws_scheduler as scheduler,
    aws_sqs as sqs,
)
from constructs import Construct

ROOT = Path(__file__).resolve().parent.parent
LAMBDA_BUILD = ROOT / "build" / "lambda"
GLUE_DATABASE = "ans_bi"


class AnsBiStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        ctx = self.node.try_get_context
        retain = bool(ctx("retainData"))

        if not (LAMBDA_BUILD / "ans_bi").exists():
            raise RuntimeError("pacote da Lambda não encontrado: rode `make build` antes do deploy")

        # --- armazenamento ------------------------------------------------------------------
        bucket = s3.Bucket(
            self,
            "Lake",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN if retain else cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=not retain,
            lifecycle_rules=[
                s3.LifecycleRule(abort_incomplete_multipart_upload_after=cdk.Duration.days(1)),
                s3.LifecycleRule(prefix="athena-results/", expiration=cdk.Duration.days(7)),
            ],
        )

        # --- fila de tarefas ----------------------------------------------------------------
        dlq = sqs.Queue(self, "TasksDlq", retention_period=cdk.Duration.days(14))
        queue = sqs.Queue(
            self,
            "Tasks",
            visibility_timeout=cdk.Duration.minutes(90),  # 6x o timeout do worker (recomendação AWS)
            retention_period=cdk.Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3),
        )

        # --- Lambdas (ARM/Graviton: ~20% mais barato que x86) --------------------------------
        code = lambda_.Code.from_asset(str(LAMBDA_BUILD))
        env = {
            "ANS_LAKE_URI": f"s3://{bucket.bucket_name}",
            "ANS_QUEUE_URL": queue.queue_url,
            "ANS_START_YEAR": str(ctx("startYear")),
            "ANS_GLUE_DATABASE": GLUE_DATABASE,
            "HOME": "/tmp",
        }
        common = dict(
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=code,
            environment=env,
        )

        planner = lambda_.Function(
            self,
            "Planner",
            handler="ans_bi.handlers.planner",
            memory_size=256,
            timeout=cdk.Duration.minutes(5),
            description="Descobre arquivos novos na ANS e enfileira no SQS",
            log_group=logs.LogGroup(
                self, "PlannerLogs", retention=logs.RetentionDays.TWO_WEEKS, removal_policy=cdk.RemovalPolicy.DESTROY
            ),
            **common,
        )

        worker_memory = int(ctx("workerMemoryMb"))
        worker = lambda_.Function(
            self,
            "Worker",
            handler="ans_bi.handlers.worker",
            memory_size=worker_memory,
            ephemeral_storage_size=cdk.Size.gibibytes(6),  # maior CSV (ICB de SP) tem ~2,5 GB
            timeout=cdk.Duration.minutes(15),
            description="Baixa um arquivo da ANS, converte para Parquet (DuckDB) e monta a camada gold",
            log_group=logs.LogGroup(
                self, "WorkerLogs", retention=logs.RetentionDays.TWO_WEEKS, removal_policy=cdk.RemovalPolicy.DESTROY
            ),
            **{
                **common,
                "environment": {
                    **env,
                    "ANS_DUCKDB_MEMORY": f"{int(worker_memory * 0.6)}MB",
                    "ANS_DUCKDB_THREADS": "2",
                },
            },
        )
        worker.add_event_source(
            sources.SqsEventSource(
                queue,
                batch_size=1,
                max_concurrency=int(ctx("workerConcurrency")),  # respeita o limite de contas novas
                report_batch_item_failures=True,
            )
        )

        bucket.grant_read(planner, "state/*")
        queue.grant_send_messages(planner)
        bucket.grant_read_write(worker)
        bucket.grant_delete(worker)
        queue.grant_send_messages(worker)
        queue.grant(worker, "sqs:GetQueueAttributes")

        # --- agendamento (EventBridge Scheduler: 14 milhões de invocações grátis/mês) --------
        scheduler_role = iam.Role(self, "SchedulerRole", assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"))
        planner.grant_invoke(scheduler_role)
        scheduler.CfnSchedule(
            self,
            "DailySchedule",
            description="Verifica diariamente as bases da ANS",
            schedule_expression=ctx("scheduleCron"),
            schedule_expression_timezone=ctx("scheduleTimezone"),
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="FLEXIBLE", maximum_window_in_minutes=30
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=planner.function_arn,
                role_arn=scheduler_role.role_arn,
                input='{"backfill": false}',
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(maximum_retry_attempts=2),
            ),
        )

        # --- catálogo e Athena (sem crawler: o worker registra as tabelas via API) -----------
        glue.CfnDatabase(
            self,
            "GlueDb",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=GLUE_DATABASE, description="Dados abertos da ANS (silver e gold)"
            ),
        )
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetTable",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:GetDatabase",
                ],
                resources=[
                    f"arn:{self.partition}:glue:{self.region}:{self.account}:catalog",
                    f"arn:{self.partition}:glue:{self.region}:{self.account}:database/{GLUE_DATABASE}",
                    f"arn:{self.partition}:glue:{self.region}:{self.account}:table/{GLUE_DATABASE}/*",
                ],
            )
        )
        workgroup = athena.CfnWorkGroup(
            self,
            "Workgroup",
            name="ans-bi",
            description="Consultas ao lake da ANS com limite de bytes por consulta",
            recursive_delete_option=True,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                bytes_scanned_cutoff_per_query=1024**3,  # 1 GB por consulta = no máximo US$ 0,005
                engine_version=athena.CfnWorkGroup.EngineVersionProperty(
                    selected_engine_version="Athena engine version 3"
                ),
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{bucket.bucket_name}/athena-results/"
                ),
            ),
        )

        # --- dados públicos da gold (S3 privado + CloudFront com OAC) -----------------------
        # O painel (Streamlit) lê daqui com ANS_GOLD_URI=https://<dominio>/data
        distribution = cloudfront.Distribution(
            self,
            "Site",
            comment="ANS BI - dados publicos (gold)",
            price_class=cloudfront.PriceClass.PRICE_CLASS_ALL,  # inclui pontos de presença no Brasil
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket, origin_path="/site"),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                compress=True,
            ),
        )

        # --- alerta de custo (orçamento da conta inteira; os 2 primeiros budgets são grátis) ----
        alert_email = ctx("alertEmail")
        if alert_email:
            limit = float(ctx("budgetUsd"))

            def notify(threshold: float, kind: str):
                return budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type=kind,
                        threshold=threshold,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(address=alert_email, subscription_type="EMAIL")],
                )

            budgets.CfnBudget(
                self,
                "Budget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name=f"{construct_id}-mensal",
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(amount=limit, unit="USD"),
                ),
                notifications_with_subscribers=[
                    notify(50, "ACTUAL"),
                    notify(100, "ACTUAL"),
                    notify(100, "FORECASTED"),
                ],
            )

        cdk.CfnOutput(self, "BucketName", value=bucket.bucket_name)
        cdk.CfnOutput(self, "PublicDataUrl", value=f"https://{distribution.distribution_domain_name}/data")
        cdk.CfnOutput(self, "PlannerFunction", value=planner.function_name)
        cdk.CfnOutput(self, "WorkerFunction", value=worker.function_name)
        cdk.CfnOutput(self, "QueueUrl", value=queue.queue_url)
        cdk.CfnOutput(self, "DeadLetterQueueUrl", value=dlq.queue_url)
        cdk.CfnOutput(self, "AthenaWorkgroup", value=workgroup.name)
        cdk.CfnOutput(self, "GlueDatabase", value=GLUE_DATABASE)

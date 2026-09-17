"""Entradas das Lambdas.

planner: disparado pelo EventBridge Scheduler; descobre arquivos novos e enfileira no SQS.
worker:  consome o SQS (1 mensagem por invocação); processa um arquivo ou reconstrói a gold.
"""

from __future__ import annotations

import json
import logging

import boto3

from . import gold, pipeline
from .config import load_settings
from .sources import SOURCES, Task
from .storage import Lake

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)

GOLD_DELAY_SECONDS = 600
GOLD_MAX_ATTEMPTS = 36  # ~6 h esperando a fila esvaziar antes de montar a gold mesmo assim

_sqs = boto3.client("sqs")


def _send(queue_url: str, bodies: list[dict], delay: int = 0) -> None:
    for i in range(0, len(bodies), 10):
        entries = [
            {"Id": str(n), "MessageBody": json.dumps(b), "DelaySeconds": delay}
            for n, b in enumerate(bodies[i : i + 10])
        ]
        resp = _sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        if resp.get("Failed"):
            raise RuntimeError(f"falha ao enfileirar: {resp['Failed']}")


def planner(event, context):
    settings = load_settings()
    lake = Lake(settings)
    sources = event.get("sources") or list(SOURCES)
    backfill = bool(event.get("backfill", False))
    tasks = pipeline.plan(settings, lake, sources, backfill=backfill)
    limit = event.get("limit")
    if limit:
        tasks = tasks[: int(limit)]
    _send(settings.queue_url, [{"type": "task", "task": t.to_dict()} for t in tasks])
    if tasks or event.get("gold"):
        _send(settings.queue_url, [{"type": "gold", "attempt": 0}], delay=GOLD_DELAY_SECONDS)
    summary: dict[str, int] = {}
    for t in tasks:
        summary[t.source] = summary.get(t.source, 0) + 1
    log.info("enfileiradas %d tarefas: %s", len(tasks), summary)
    return {"enqueued": len(tasks), "by_source": summary, "backfill": backfill}


def _pending_messages(queue_url: str) -> int:
    attrs = _sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ],
    )["Attributes"]
    return sum(int(v) for v in attrs.values())


def _handle(body: dict, settings, lake: Lake) -> dict:
    if body["type"] == "task":
        return pipeline.run_task(settings, lake, Task.from_dict(body["task"]))
    if body["type"] == "gold":
        attempt = int(body.get("attempt", 0))
        # a própria mensagem conta como "em voo"; qualquer coisa além dela é trabalho pendente
        others = _pending_messages(settings.queue_url) - 1
        if others > 0 and attempt < GOLD_MAX_ATTEMPTS:
            _send(settings.queue_url, [{"type": "gold", "attempt": attempt + 1}], delay=GOLD_DELAY_SECONDS)
            return {"status": "deferred", "pending": others, "attempt": attempt}
        return gold.build(settings, lake, force=bool(body.get("force")))
    raise ValueError(f"tipo de mensagem desconhecido: {body['type']}")


def worker(event, context):
    settings = load_settings()
    lake = Lake(settings)
    if "Records" not in event:  # invocação direta (ex.: aws lambda invoke com {"type": "gold"})
        return _handle(event, settings, lake)

    failures = []
    for record in event["Records"]:
        try:
            log.info("resultado: %s", _handle(json.loads(record["body"]), settings, lake))
        except Exception:
            log.exception("falha na mensagem %s", record["messageId"])
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}

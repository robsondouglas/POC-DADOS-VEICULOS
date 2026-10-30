"""Lambda de Ingestão.

Fluxo (acionada por SQS, originada de SNS/S3):
  1. Para cada mensagem, extrai bucket/key do evento S3.
  2. Lê o arquivo, parseia as linhas (descarte silencioso de malformadas) e agrupa por lote.
  3. Para cada lote: garante o registro de controle (condicional) e enfileira a verificação de SLA na criação.
  4. Insere cada veículo de forma idempotente e incrementa o contador atômico.
  5. Quando o lote completa, marca PREENCHIDO (passo único) e dispara a carga da SOT.
"""
from __future__ import annotations

import json
import os
import urllib.parse

import boto3

from src.common.parsing import group_by_lote, parse_lines
from src.common.repository import LoteRepository
from src.common.sla_queue import SlaQueueClient

_s3 = None
_lambda = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda")
    return _lambda


def _read_s3_lines(bucket: str, key: str) -> list[str]:
    obj = _s3_client().get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read().decode("utf-8")
    return body.splitlines()


def _iter_s3_records(event: dict):
    """Extrai (bucket, key) de mensagens SQS que encapsulam notificação SNS -> S3."""
    for sqs_record in event.get("Records", []):
        body = json.loads(sqs_record["body"])
        # SNS envelopa a mensagem do S3 em 'Message' (string JSON).
        if "Message" in body:
            body = json.loads(body["Message"])
        for s3_rec in body.get("Records", []):
            bucket = s3_rec["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(s3_rec["s3"]["object"]["key"])
            yield bucket, key


def _trigger_sot_load(lote: str) -> None:
    function_name = os.environ.get("CARGA_SOT_FUNCTION")
    if not function_name:
        return
    _lambda_client().invoke(
        FunctionName=function_name,
        InvocationType="Event",  # assíncrono
        Payload=json.dumps({"lote": lote}).encode("utf-8"),
    )


def handler(event, context=None):
    repo = LoteRepository(os.environ["TABLE_NAME"])
    sla_queue = SlaQueueClient()

    for bucket, key in _iter_s3_records(event):
        lines = _read_s3_lines(bucket, key)
        por_lote = group_by_lote(parse_lines(lines))

        for lote, registros in por_lote.items():
            lote_items = registros[0].lote_items
            control = repo.ensure_control(lote, lote_items)
            if control.created:
                sla_queue.schedule_sla(lote)

            for record in registros:
                result = repo.insert_vehicle(record)
                if result.inserted and result.completed:
                    # Transição única: só uma execução conduz a conclusão.
                    if repo.mark_preenchido(lote):
                        _trigger_sot_load(lote)

    return {"status": "ok"}

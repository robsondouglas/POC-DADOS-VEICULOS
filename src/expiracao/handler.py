"""Lambda de Expiração (SLA).

Acionada pelo EventBridge Scheduler após 30s, com payload {"lote": "<id>"}.
Marca o lote como EXPIRADO somente se o status ainda for PREENCHENDO e,
nesse caso, publica uma notificação de FALHA no SNS de resultado.
"""
from __future__ import annotations

import json
import os

import boto3

from src.common.repository import LoteRepository

_sns = None


def _sns_client():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    return _sns


def _publish_falha(lote: str) -> None:
    topic_arn = os.environ.get("SNS_RESULTADO_ARN")
    if not topic_arn:
        return
    _sns_client().publish(
        TopicArn=topic_arn,
        Subject="SLA FALHA",
        Message=json.dumps({"lote": lote, "resultado": "FALHA", "motivo": "EXPIRADO"}),
    )


def handler(event, context=None):
    lote = event["lote"]
    repo = LoteRepository(os.environ["TABLE_NAME"])

    if repo.mark_expirado_if_preenchendo(lote):
        _publish_falha(lote)
        return {"lote": lote, "expirado": True}

    # Já estava PREENCHIDO/CONCLUIDO (ou inexistente): não expira.
    return {"lote": lote, "expirado": False}

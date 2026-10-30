"""Lambda de Expiração (SLA).

Acionada pela fila SQS de SLA (mensagem com DelaySeconds=30), com corpo
{"lote": "<id>"}. Marca o lote como EXPIRADO somente se o status ainda for
PREENCHENDO e, nesse caso, publica uma notificação de FALHA no SNS de resultado.

A mensagem chega mesmo que o lote já esteja PREENCHIDO/CONCLUIDO; nesse caso a
transição condicional falha silenciosamente e nada acontece (descarte barato).
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from src.common.repository import LoteRepository

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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


def _lotes_do_evento(event: dict):
    """Extrai os IDs de lote do evento.

    Suporta o envelope SQS (Records[].body = JSON {"lote": ...}) e a invocação
    direta com {"lote": ...} (compatibilidade com testes e chamadas pontuais).
    """
    if "Records" in event:
        for record in event["Records"]:
            body = json.loads(record["body"])
            yield body["lote"]
    else:
        yield event["lote"]


def _expira_lote(lote: str, repo: LoteRepository) -> bool:
    if repo.mark_expirado_if_preenchendo(lote):
        _publish_falha(lote)
        logger.info("lote=%s expirado=True (transicao PREENCHENDO->EXPIRADO)", lote)
        return True
    # Já estava PREENCHIDO/CONCLUIDO (ou inexistente): não expira.
    logger.info("lote=%s expirado=False (status != PREENCHENDO; nenhuma transicao)", lote)
    return False


def handler(event, context=None):
    repo = LoteRepository(os.environ["TABLE_NAME"])
    resultados = [
        {"lote": lote, "expirado": _expira_lote(lote, repo)}
        for lote in _lotes_do_evento(event)
    ]
    # Mantém a forma de retorno single-item quando houver apenas um lote,
    # preservando compatibilidade com invocações diretas.
    if len(resultados) == 1:
        return resultados[0]
    return {"resultados": resultados}

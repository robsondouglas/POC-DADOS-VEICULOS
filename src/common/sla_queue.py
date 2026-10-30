"""Agendamento do SLA do lote via SQS com entrega atrasada (DelaySeconds).

Substitui o EventBridge Scheduler: ao criar o registro de controle, a ingestão
envia uma mensagem para a fila de SLA com DelaySeconds = SLA_SECONDS. Após o
atraso, a mensagem fica visível e aciona a Lambda de Expiração.

Vantagens sobre o Scheduler `at(...)`:
- Precisão muito melhor para intervalos curtos (o `at()` atrasa dezenas de
  segundos; o DelaySeconds da SQS respeita o atraso com desvio de poucos segundos).
- Sem permissão de invocação / role dedicada / Lambda::Permission (menos partes).
- DLQ e retry são nativos da SQS (RedrivePolicy + maxReceiveCount).

A mensagem é sempre entregue, mesmo que o lote já esteja PREENCHIDO/CONCLUIDO.
Isso é inofensivo: a transição para EXPIRADO é condicional (só ocorre se o
status ainda for PREENCHENDO), então mensagens de lotes concluídos são
descartadas de forma barata pela Lambda de Expiração.
"""
from __future__ import annotations

import json
import os

import boto3

from .constants import SLA_SECONDS


class SlaQueueClient:
    def __init__(self, sqs=None):
        self._client = sqs or boto3.client("sqs")
        self._queue_url = os.environ["SLA_QUEUE_URL"]

    def schedule_sla(self, lote: str) -> None:
        """Enfileira a verificação de SLA do lote para daqui a SLA_SECONDS."""
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"lote": lote}),
            DelaySeconds=SLA_SECONDS,
        )

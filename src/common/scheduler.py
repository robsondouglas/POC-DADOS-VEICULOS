"""Criação e remoção de schedules one-time no EventBridge Scheduler (SLA do lote)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from .constants import SLA_SECONDS


class SchedulerClient:
    def __init__(self, scheduler=None):
        self._client = scheduler or boto3.client("scheduler")
        self._group = os.environ["SCHEDULER_GROUP"]
        self._target_arn = os.environ["SCHEDULER_TARGET_LAMBDA_ARN"]
        self._role_arn = os.environ["SCHEDULER_ROLE_ARN"]

    @staticmethod
    def _at_expression(seconds: int) -> str:
        """Expressão one-time at(...) para agora + `seconds`, em UTC.

        O EventBridge Scheduler não aceita rate() em segundos (mínimo é minuto),
        então usamos um schedule de disparo único no formato at(yyyy-mm-ddThh:mm:ss).
        """
        fire_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        return f"at({fire_at.strftime('%Y-%m-%dT%H:%M:%S')})"

    def create_sla_schedule(self, lote: str) -> None:
        """Cria um schedule one-time que dispara após SLA_SECONDS, ID = lote.

        Idempotente: se o schedule já existir, não falha.
        """
        try:
            self._client.create_schedule(
                Name=lote,
                GroupName=self._group,
                ScheduleExpression=self._at_expression(SLA_SECONDS),
                ScheduleExpressionTimezone="UTC",
                FlexibleTimeWindow={"Mode": "OFF"},
                Target={
                    "Arn": self._target_arn,
                    "RoleArn": self._role_arn,
                    "Input": json.dumps({"lote": lote}),
                },
                ActionAfterCompletion="DELETE",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConflictException":
                return
            raise

    def delete_sla_schedule(self, lote: str) -> None:
        """Remove o schedule do lote. Ignora se já não existir."""
        try:
            self._client.delete_schedule(Name=lote, GroupName=self._group)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                return
            raise


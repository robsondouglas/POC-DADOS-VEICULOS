"""Acesso à tabela DynamoDB (Single Table Design).

PK = lote, SK = placa. O registro de controle usa SK = CONTROL_PLACA ('0000000').

Garantias implementadas:
- Criação condicional do controle (não recria lote existente).
- Inserção idempotente de veículo (não duplica mesma placa no lote).
- Incremento atômico do contador (ADD), retornando o novo valor.
- Transição de status condicional (passo único na conclusão).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

from .constants import CONTROL_PLACA, TTL_SECONDS, Status
from .parsing import VehicleRecord


@dataclass
class ControlResult:
    created: bool  # True se o controle foi criado nesta chamada


@dataclass
class VehicleInsertResult:
    inserted: bool  # True se o veículo foi inserido (False = duplicado)
    new_count: int | None  # novo valor de itens_registrados, se inserido
    completed: bool  # True se este insert fechou o lote (count == lote_items)


class LoteRepository:
    def __init__(self, table_name: str, dynamodb_resource=None):
        self._table = (dynamodb_resource or boto3.resource("dynamodb")).Table(table_name)

    def _ttl(self) -> int:
        return int(time.time()) + TTL_SECONDS

    @staticmethod
    def _status_ts_attr(status: str) -> str:
        """Nome do atributo que guarda o epoch da transição para `status`."""
        return f"ts_{status}"

    def ensure_control(self, lote: str, lote_items: int) -> ControlResult:
        """Cria o registro de controle do lote se ainda não existir.

        Idempotente: se já existir, não recria (retorna created=False).
        """
        try:
            self._table.put_item(
                Item={
                    "PK": lote,
                    "SK": CONTROL_PLACA,
                    "lote_items": lote_items,
                    "itens_registrados": 0,
                    "status": Status.PREENCHENDO,
                    self._status_ts_attr(Status.PREENCHENDO): int(time.time()),
                    "ttl": self._ttl(),
                },
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            return ControlResult(created=True)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return ControlResult(created=False)
            raise

    def insert_vehicle(self, record: VehicleRecord) -> VehicleInsertResult:
        """Insere um veículo de forma idempotente e incrementa o contador.

        - Put condicional (attribute_not_exists) garante idempotência.
        - Se inserido, incrementa itens_registrados atomicamente (ADD) e
          verifica se o lote foi completado.
        - Se duplicado, não incrementa.
        """
        try:
            self._table.put_item(
                Item={
                    "PK": record.lote,
                    "SK": record.placa,
                    "modelo": record.modelo,
                    "fabricante": record.fabricante,
                    "ano_fabricacao": record.ano_fabricacao,
                    "ttl": self._ttl(),
                },
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return VehicleInsertResult(inserted=False, new_count=None, completed=False)
            raise

        new_count = self._increment_counter(record.lote)
        lote_items = self._get_lote_items(record.lote)
        completed = lote_items is not None and new_count >= lote_items
        return VehicleInsertResult(inserted=True, new_count=new_count, completed=completed)

    def _increment_counter(self, lote: str) -> int:
        resp = self._table.update_item(
            Key={"PK": lote, "SK": CONTROL_PLACA},
            UpdateExpression="ADD itens_registrados :um",
            ExpressionAttributeValues={":um": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["itens_registrados"])

    def _get_lote_items(self, lote: str) -> int | None:
        resp = self._table.get_item(
            Key={"PK": lote, "SK": CONTROL_PLACA},
            ProjectionExpression="lote_items",
        )
        item = resp.get("Item")
        return int(item["lote_items"]) if item else None

    def mark_preenchido(self, lote: str) -> bool:
        """Transição PREENCHENDO -> PREENCHIDO com condição (passo único).

        Retorna True se esta chamada efetuou a transição; False se outra já efetuou.
        """
        return self._conditional_status(
            lote, new_status=Status.PREENCHIDO, expected=Status.PREENCHENDO
        )

    def mark_concluido(self, lote: str) -> bool:
        """Transição PREENCHIDO -> CONCLUIDO (após sucesso da carga da SOT)."""
        return self._conditional_status(
            lote, new_status=Status.CONCLUIDO, expected=Status.PREENCHIDO
        )

    def mark_expirado_if_preenchendo(self, lote: str) -> bool:
        """Marca EXPIRADO somente se o status ainda for PREENCHENDO."""
        return self._conditional_status(
            lote, new_status=Status.EXPIRADO, expected=Status.PREENCHENDO
        )

    def _conditional_status(self, lote: str, new_status: str, expected: str) -> bool:
        ts_attr = self._status_ts_attr(new_status)
        try:
            self._table.update_item(
                Key={"PK": lote, "SK": CONTROL_PLACA},
                UpdateExpression="SET #s = :novo, #ts = :epoch",
                ConditionExpression="#s = :esperado",
                ExpressionAttributeNames={"#s": "status", "#ts": ts_attr},
                ExpressionAttributeValues={
                    ":novo": new_status,
                    ":esperado": expected,
                    ":epoch": int(time.time()),
                },
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def get_status(self, lote: str) -> str | None:
        resp = self._table.get_item(
            Key={"PK": lote, "SK": CONTROL_PLACA},
            ProjectionExpression="#s",
            ExpressionAttributeNames={"#s": "status"},
        )
        item = resp.get("Item")
        return item["status"] if item else None

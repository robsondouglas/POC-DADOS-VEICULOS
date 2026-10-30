"""Lambda de Carga da SOT.

Acionada (assíncrono) pela conclusão do lote, com payload {"lote": "<id>"}.

Passos:
  1. Lista os objetos da SOR no prefixo do lote e consolida os veículos (dedup por placa).
  2. Valida que a contagem consolidada == lote_items (trata consistência eventual da SOR).
     Se faltar registro, levanta exceção para retry (mantém status PREENCHIDO).
  3. Escreve 1 arquivo Parquet por lote na SOT (via pyarrow).
  4. Marca CONCLUIDO, remove o schedule e publica SUCESSO no SNS.
"""
from __future__ import annotations

import io
import json
import os

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

from src.common.constants import SOT_COLUMNS
from src.common.repository import LoteRepository
from src.common.scheduler import SchedulerClient

_s3 = None
_sns = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _sns_client():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    return _sns


class SorIncompleto(Exception):
    """A SOR ainda não tem todos os registros do lote (retry)."""


def _read_sor_vehicles(bucket: str, lote: str) -> dict[str, dict]:
    """Lê todos os objetos SOR do lote e consolida veículos, deduplicando por placa."""
    prefix = f"sor/lote={lote}/"
    paginator = _s3_client().get_paginator("list_objects_v2")
    por_placa: dict[str, dict] = {}
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            body = _s3_client().get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            for line in body.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                v = json.loads(line)
                por_placa[v["placa"]] = v
    return por_placa


def _write_parquet(bucket: str, lote: str, vehicles: list[dict]) -> str:
    # Ordena por placa para saída determinística.
    vehicles = sorted(vehicles, key=lambda v: v["placa"])
    columns = {col: [v[col] for v in vehicles] for col in SOT_COLUMNS}
    table = pa.table(columns)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    key = f"sot/lote={lote}/dados.parquet"
    _s3_client().put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return key


def _publish_sucesso(lote: str, key: str) -> None:
    topic_arn = os.environ.get("SNS_RESULTADO_ARN")
    if not topic_arn:
        return
    _sns_client().publish(
        TopicArn=topic_arn,
        Subject="SLA SUCESSO",
        Message=json.dumps(
            {"lote": lote, "resultado": "SUCESSO", "sot_key": key}
        ),
    )


def handler(event, context=None):
    lote = event["lote"]
    sor_bucket = os.environ["BUCKET_SOR"]
    sot_bucket = os.environ["BUCKET_SOT"]

    repo = LoteRepository(os.environ["TABLE_NAME"])

    lote_items = repo._get_lote_items(lote)
    if lote_items is None:
        raise ValueError(f"Lote {lote} sem registro de controle")

    vehicles = list(_read_sor_vehicles(sor_bucket, lote).values())
    if len(vehicles) < lote_items:
        # Consistência eventual: ainda faltam registros na SOR. Retry.
        raise SorIncompleto(
            f"Lote {lote}: SOR tem {len(vehicles)} de {lote_items}"
        )

    key = _write_parquet(sot_bucket, lote, vehicles)

    repo.mark_concluido(lote)
    SchedulerClient().delete_sla_schedule(lote)
    _publish_sucesso(lote, key)

    return {"lote": lote, "veiculos": len(vehicles), "sot_key": key}

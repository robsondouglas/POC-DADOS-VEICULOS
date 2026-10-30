"""Lambda Consumidora SOR.

Consome micro-batches do Kinesis (originados do DynamoDB Stream) e grava 1 objeto
por micro-batch, particionado por lote, no bucket SOR.

- Como o Kinesis particiona por lote, um micro-batch tende a conter registros do mesmo lote;
  ainda assim, o código agrupa por lote defensivamente e grava um objeto por lote.
- Não há read-modify-write: cada micro-batch gera objeto(s) novo(s) com nome único.
- Registros de controle (placa '0000000') são ignorados (filtro de reforço, além do filtro no Stream).
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid

import boto3

from src.common.constants import CONTROL_PLACA

_s3 = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _unwrap_dynamo(image: dict) -> dict:
    """Converte uma imagem DynamoDB tipada ({'S':..}/{'N':..}) em dict simples."""
    out = {}
    for key, typed in image.items():
        if "S" in typed:
            out[key] = typed["S"]
        elif "N" in typed:
            num = typed["N"]
            out[key] = int(num) if num.isdigit() or (num.lstrip("-").isdigit()) else float(num)
        elif "BOOL" in typed:
            out[key] = typed["BOOL"]
        elif "NULL" in typed:
            out[key] = None
        else:
            out[key] = typed
    return out


def _vehicle_from_image(image: dict) -> dict | None:
    """Extrai um registro de veículo da NEW_IMAGE; ignora controle e não-veículos."""
    item = _unwrap_dynamo(image)
    lote = item.get("PK")
    placa = item.get("SK")
    if lote is None or placa is None or placa == CONTROL_PLACA:
        return None
    # Veículo precisa ter os campos de dados; controle não tem.
    if "modelo" not in item:
        return None
    return {
        "lote": lote,
        "placa": placa,
        "ano_fabricacao": int(item["ano_fabricacao"]),
        "modelo": item.get("modelo", ""),
        "fabricante": item.get("fabricante", ""),
    }


def _iter_vehicles(event: dict):
    """Itera veículos a partir dos registros Kinesis (payload DynamoDB Stream)."""
    for record in event.get("Records", []):
        raw = base64.b64decode(record["kinesis"]["data"])
        payload = json.loads(raw)
        # Suporta tanto o envelope do DynamoDB Stream quanto a NEW_IMAGE direta.
        image = payload.get("dynamodb", {}).get("NewImage") or payload.get("NewImage")
        if not image:
            continue
        vehicle = _vehicle_from_image(image)
        if vehicle is not None:
            yield vehicle


def handler(event, context=None):
    bucket = os.environ["BUCKET_SOR"]
    por_lote: dict[str, list[dict]] = {}
    for vehicle in _iter_vehicles(event):
        por_lote.setdefault(vehicle["lote"], []).append(vehicle)

    written = 0
    for lote, vehicles in por_lote.items():
        key = f"sor/lote={lote}/{int(time.time()*1000)}-{uuid.uuid4().hex}.json"
        body = "\n".join(json.dumps(v) for v in vehicles).encode("utf-8")
        _s3_client().put_object(Bucket=bucket, Key=key, Body=body)
        written += 1

    return {"objetos_gravados": written}

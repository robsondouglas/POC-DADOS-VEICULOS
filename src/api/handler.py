"""Lambda da API de visualização (camada de apresentação da POC).

Endpoints (API Gateway HTTP API):
  GET /api/lotes          -> lista de IDs de lote presentes na SOT (via ListObjectsV2)
  GET /api/lotes/{lote}   -> veículos do lote (lê o Parquet da SOT via DuckDB)

Somente leitura. O parâmetro {lote} é validado por allowlist e passado como
parâmetro da query DuckDB (nunca concatenado), evitando injeção.
"""
from __future__ import annotations

import json
import os
import re

import boto3

_s3 = None
_LOTE_RE = re.compile(r"^[A-Za-z0-9]+$")


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body),
    }


def _list_lotes(bucket: str) -> list[str]:
    paginator = _s3_client().get_paginator("list_objects_v2")
    lotes: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix="sot/lote=", Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            # 'sot/lote=000123/' -> '000123'
            prefix = cp["Prefix"]
            lote = prefix[len("sot/lote="):].rstrip("/")
            if lote:
                lotes.append(lote)
    return sorted(lotes)


def _object_exists(bucket: str, key: str) -> bool:
    try:
        _s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except _s3_client().exceptions.ClientError:
        return False


def _read_lote(bucket: str, lote: str) -> list[dict]:
    """Lê o Parquet do lote na SOT.

    Em vez de usar o httpfs do DuckDB (que no Lambda falha por falta de home
    directory gravável e por depender de download da extensão em runtime),
    baixamos o objeto para /tmp via boto3 e lemos o arquivo local. Os Parquet
    da SOT são pequenos (1 por lote), então isto é eficiente e confiável.
    """
    import duckdb

    key = f"sot/lote={lote}/dados.parquet"
    local_path = f"/tmp/{lote}.parquet"
    _s3_client().download_file(bucket, key, local_path)

    con = duckdb.connect()
    con.execute("SET home_directory='/tmp';")
    try:
        rows = con.execute(
            "SELECT lote, placa, ano_fabricacao, modelo, fabricante "
            "FROM read_parquet(?)",
            [local_path],
        ).fetchall()
    finally:
        con.close()
        try:
            os.remove(local_path)
        except OSError:
            pass

    cols = ["lote", "placa", "ano_fabricacao", "modelo", "fabricante"]
    return [dict(zip(cols, r)) for r in rows]


def _route(event) -> tuple[str, str | None]:
    """Extrai (recurso, lote) do evento do API Gateway HTTP API."""
    path = event.get("rawPath") or event.get("path", "")
    params = event.get("pathParameters") or {}
    lote = params.get("lote")
    return path, lote


def handler(event, context=None):
    bucket = os.environ["BUCKET_SOT"]
    path, lote = _route(event)

    if lote is not None or "/api/lotes/" in path:
        if lote is None:
            lote = path.rsplit("/", 1)[-1]
        if not _LOTE_RE.match(lote or ""):
            return _response(400, {"erro": "lote invalido"})
        key = f"sot/lote={lote}/dados.parquet"
        if not _object_exists(bucket, key):
            return _response(404, {"erro": "lote nao encontrado"})
        return _response(200, {"lote": lote, "veiculos": _read_lote(bucket, lote)})

    # GET /api/lotes
    return _response(200, {"lotes": _list_lotes(bucket)})

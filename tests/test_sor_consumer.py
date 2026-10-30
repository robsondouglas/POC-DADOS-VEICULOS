"""Testes da Lambda Consumidora SOR."""
import base64
import json

import boto3
import pytest
from moto import mock_aws

BUCKET = "sor-test"


def _kinesis_record(image: dict):
    payload = {"dynamodb": {"NewImage": image}}
    data = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    return {"kinesis": {"data": data}}


def _veiculo_image(lote, placa, modelo="GOL", fab="VW", ano="2020"):
    return {
        "PK": {"S": lote},
        "SK": {"S": placa},
        "modelo": {"S": modelo},
        "fabricante": {"S": fab},
        "ano_fabricacao": {"N": ano},
    }


def _controle_image(lote):
    return {
        "PK": {"S": lote},
        "SK": {"S": "0000000"},
        "lote_items": {"N": "5"},
        "itens_registrados": {"N": "0"},
        "status": {"S": "PREENCHENDO"},
    }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("BUCKET_SOR", BUCKET)


def test_grava_objeto_por_lote_e_ignora_controle(env):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)

        event = {
            "Records": [
                _kinesis_record(_veiculo_image("000001", "AAA1111")),
                _kinesis_record(_veiculo_image("000001", "BBB2222")),
                _kinesis_record(_controle_image("000001")),  # ignorado
            ]
        }

        import src.sor_consumer.handler as h

        out = h.handler(event)
        assert out["objetos_gravados"] == 1

        objs = s3.list_objects_v2(Bucket=BUCKET, Prefix="sor/lote=000001/")["Contents"]
        assert len(objs) == 1
        body = s3.get_object(Bucket=BUCKET, Key=objs[0]["Key"])["Body"].read().decode()
        placas = {json.loads(l)["placa"] for l in body.splitlines()}
        assert placas == {"AAA1111", "BBB2222"}


def test_agrupa_multiplos_lotes_em_objetos_separados(env):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)

        event = {
            "Records": [
                _kinesis_record(_veiculo_image("000001", "AAA1111")),
                _kinesis_record(_veiculo_image("000002", "BBB2222")),
            ]
        }

        import src.sor_consumer.handler as h

        out = h.handler(event)
        assert out["objetos_gravados"] == 2
        assert len(s3.list_objects_v2(Bucket=BUCKET, Prefix="sor/lote=000001/")["Contents"]) == 1
        assert len(s3.list_objects_v2(Bucket=BUCKET, Prefix="sor/lote=000002/")["Contents"]) == 1

"""Testes da Lambda de Carga da SOT."""
import io
import json

import boto3
import pyarrow.parquet as pq
import pytest
from moto import mock_aws

from src.common.constants import Status
from src.common.repository import LoteRepository

TABLE = "lotes-test"
SOR = "sor-test"
SOT = "sot-test"


def _create_table(dynamodb):
    dynamodb.create_table(
        TableName=TABLE,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _seed_sor(s3, lote, veiculos, nome="batch1.json"):
    body = "\n".join(json.dumps(v) for v in veiculos).encode("utf-8")
    s3.put_object(Bucket=SOR, Key=f"sor/lote={lote}/{nome}", Body=body)


def _veiculo(lote, placa, ano=2020, modelo="GOL", fab="VW"):
    return {
        "lote": lote,
        "placa": placa,
        "ano_fabricacao": ano,
        "modelo": modelo,
        "fabricante": fab,
    }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_SOR", SOR)
    monkeypatch.setenv("BUCKET_SOT", SOT)
    monkeypatch.setenv("SNS_RESULTADO_ARN", "arn:aws:sns:us-east-1:123:topic")


def test_carga_sot_sucesso(env):
    from unittest.mock import patch

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=SOR)
        s3.create_bucket(Bucket=SOT)

        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        repo.ensure_control("000001", 2)
        repo.mark_preenchido("000001")

        _seed_sor(
            s3, "000001", [_veiculo("000001", "AAA1111"), _veiculo("000001", "BBB2222")]
        )

        import src.carga_sot.handler as h

        with patch.object(h, "_sns_client") as sns_fn:
            out = h.handler({"lote": "000001"})
            assert out["veiculos"] == 2
            sns_fn.return_value.publish.assert_called_once()

        # status concluído
        assert repo.get_status("000001") == Status.CONCLUIDO

        # Parquet gravado e legível
        raw = s3.get_object(Bucket=SOT, Key="sot/lote=000001/dados.parquet")["Body"].read()
        table = pq.read_table(io.BytesIO(raw))
        assert table.num_rows == 2
        assert set(table.column_names) == {
            "lote",
            "placa",
            "ano_fabricacao",
            "modelo",
            "fabricante",
        }


def test_carga_sot_incompleta_levanta_para_retry(env):
    from unittest.mock import patch

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=SOR)
        s3.create_bucket(Bucket=SOT)

        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        repo.ensure_control("000002", 3)
        repo.mark_preenchido("000002")

        # SOR só tem 1 de 3
        _seed_sor(s3, "000002", [_veiculo("000002", "AAA1111")])

        import src.carga_sot.handler as h

        with patch.object(h, "_sns_client"):
            with pytest.raises(h.SorIncompleto):
                h.handler({"lote": "000002"})

        # não concluiu
        assert repo.get_status("000002") == Status.PREENCHIDO


def test_carga_sot_dedup_por_placa(env):
    from unittest.mock import patch

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=SOR)
        s3.create_bucket(Bucket=SOT)

        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        repo.ensure_control("000003", 2)
        repo.mark_preenchido("000003")

        # placa AAA1111 duplicada em dois batches; total único = 2
        _seed_sor(s3, "000003", [_veiculo("000003", "AAA1111")], nome="b1.json")
        _seed_sor(
            s3,
            "000003",
            [_veiculo("000003", "AAA1111"), _veiculo("000003", "BBB2222")],
            nome="b2.json",
        )

        import src.carga_sot.handler as h

        with patch.object(h, "_sns_client"):
            out = h.handler({"lote": "000003"})
            assert out["veiculos"] == 2

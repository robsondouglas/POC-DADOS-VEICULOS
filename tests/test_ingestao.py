"""Testes da Lambda de ingestão com moto (S3 + DynamoDB) e stubs de scheduler/lambda."""
import json
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from src.common.constants import Status
from src.common.repository import LoteRepository

TABLE = "lotes-test"
BUCKET = "ingestao-test"


def make_line(lote, placa, lote_items="0002", ano="2020", modelo="GOL", fab="VW"):
    return f"{lote:<6}{lote_items:<4}{placa:<7}{ano:<4}{modelo:<20}{fab:<20}"


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


def _sqs_event(bucket, key):
    s3_event = {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}
    sns_envelope = {"Message": json.dumps(s3_event)}
    return {"Records": [{"body": json.dumps(sns_envelope)}]}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("SCHEDULER_GROUP", "grp")
    monkeypatch.setenv("SCHEDULER_TARGET_LAMBDA_ARN", "arn:lambda")
    monkeypatch.setenv("SCHEDULER_ROLE_ARN", "arn:role")
    monkeypatch.setenv("CARGA_SOT_FUNCTION", "carga-sot")


def _put_file(s3, key, content):
    s3.put_object(Bucket=BUCKET, Key=key, Body=content.encode("utf-8"))


def test_ingestao_fluxo_completo(env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)

        conteudo = "\n".join(
            [
                make_line("000001", "AAA1111"),
                make_line("000001", "BBB2222"),
                "linha malformada",  # descartada
            ]
        )
        _put_file(s3, "arquivo1.txt", conteudo)

        import src.ingestao.handler as h

        with patch.object(h, "SchedulerClient") as sched_cls, patch.object(
            h, "_lambda_client"
        ) as lambda_fn:
            sched = sched_cls.return_value
            lambda_client = lambda_fn.return_value
            h.handler(_sqs_event(BUCKET, "arquivo1.txt"))

            # schedule criado uma vez (lote novo)
            sched.create_sla_schedule.assert_called_once_with("000001")
            # carga da SOT disparada ao completar (2/2)
            lambda_client.invoke.assert_called_once()
            _, kwargs = lambda_client.invoke.call_args
            assert kwargs["FunctionName"] == "carga-sot"
            assert json.loads(kwargs["Payload"])["lote"] == "000001"

        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        assert repo.get_status("000001") == Status.PREENCHIDO


def test_ingestao_idempotente_em_reenvio(env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)

        conteudo = "\n".join(
            [make_line("000009", "AAA1111"), make_line("000009", "BBB2222")]
        )
        _put_file(s3, "dup.txt", conteudo)

        import src.ingestao.handler as h

        with patch.object(h, "SchedulerClient"), patch.object(h, "_lambda_client"):
            # processa o mesmo arquivo duas vezes
            h.handler(_sqs_event(BUCKET, "dup.txt"))
            h.handler(_sqs_event(BUCKET, "dup.txt"))

        table = dynamodb.Table(TABLE)
        ctrl = table.get_item(Key={"PK": "000009", "SK": "0000000"})["Item"]
        # contador não ultrapassa lote_items apesar do reenvio
        assert int(ctrl["itens_registrados"]) == 2


def test_ingestao_multiplos_lotes_no_mesmo_arquivo(env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)

        conteudo = "\n".join(
            [
                make_line("000010", "AAA1111", lote_items="0001"),
                make_line("000011", "BBB2222", lote_items="0002"),
            ]
        )
        _put_file(s3, "multi.txt", conteudo)

        import src.ingestao.handler as h

        with patch.object(h, "SchedulerClient") as sched_cls, patch.object(
            h, "_lambda_client"
        ):
            sched = sched_cls.return_value
            h.handler(_sqs_event(BUCKET, "multi.txt"))
            # dois lotes novos -> dois schedules
            assert sched.create_sla_schedule.call_count == 2

        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        # lote 000010 completou (1/1); 000011 ainda não (1/2)
        assert repo.get_status("000010") == Status.PREENCHIDO
        assert repo.get_status("000011") == Status.PREENCHENDO

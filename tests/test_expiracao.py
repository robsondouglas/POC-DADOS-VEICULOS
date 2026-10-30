"""Testes da Lambda de expiração (SLA)."""
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from src.common.constants import Status
from src.common.repository import LoteRepository

TABLE = "lotes-test"


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


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("SNS_RESULTADO_ARN", "arn:aws:sns:us-east-1:123:topic")


def test_expira_quando_preenchendo(env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        repo.ensure_control("000001", 5)

        import src.expiracao.handler as h

        with patch.object(h, "_sns_client") as sns_fn:
            sns = sns_fn.return_value
            out = h.handler({"lote": "000001"})

            assert out["expirado"] is True
            sns.publish.assert_called_once()
            assert repo.get_status("000001") == Status.EXPIRADO


def test_nao_expira_quando_concluido(env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        repo.ensure_control("000002", 1)
        repo.mark_preenchido("000002")
        repo.mark_concluido("000002")

        import src.expiracao.handler as h

        with patch.object(h, "_sns_client") as sns_fn:
            sns = sns_fn.return_value
            out = h.handler({"lote": "000002"})

            assert out["expirado"] is False
            sns.publish.assert_not_called()
            assert repo.get_status("000002") == Status.CONCLUIDO


def test_nao_expira_quando_preenchido(env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)
        repo = LoteRepository(TABLE, dynamodb_resource=dynamodb)
        repo.ensure_control("000003", 2)
        repo.mark_preenchido("000003")

        import src.expiracao.handler as h

        with patch.object(h, "_sns_client") as sns_fn:
            sns = sns_fn.return_value
            out = h.handler({"lote": "000003"})

            assert out["expirado"] is False
            sns.publish.assert_not_called()
            assert repo.get_status("000003") == Status.PREENCHIDO

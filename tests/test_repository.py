"""Testes do LoteRepository usando moto (DynamoDB mock)."""
import boto3
import pytest
from moto import mock_aws

from src.common.constants import CONTROL_PLACA, Status
from src.common.parsing import VehicleRecord
from src.common.repository import LoteRepository

TABLE = "lotes-test"


def _make_table(dynamodb):
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


def _rec(lote="000001", placa="AAA1111", lote_items=2):
    return VehicleRecord(
        lote=lote,
        lote_items=lote_items,
        placa=placa,
        ano_fabricacao=2020,
        modelo="GOL",
        fabricante="VW",
    )


@pytest.fixture
def repo():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _make_table(dynamodb)
        yield LoteRepository(TABLE, dynamodb_resource=dynamodb)


def test_ensure_control_cria_uma_vez(repo):
    assert repo.ensure_control("000001", 2).created is True
    # segunda chamada não recria
    assert repo.ensure_control("000001", 2).created is False


def test_insert_vehicle_idempotente(repo):
    repo.ensure_control("000001", 2)
    r1 = repo.insert_vehicle(_rec(placa="AAA1111"))
    assert r1.inserted is True
    assert r1.new_count == 1
    assert r1.completed is False

    # reinserção da mesma placa não incrementa
    r2 = repo.insert_vehicle(_rec(placa="AAA1111"))
    assert r2.inserted is False
    assert r2.new_count is None
    assert r2.completed is False


def test_completude_ao_atingir_lote_items(repo):
    repo.ensure_control("000001", 2)
    repo.insert_vehicle(_rec(placa="AAA1111"))
    r = repo.insert_vehicle(_rec(placa="BBB2222"))
    assert r.inserted is True
    assert r.new_count == 2
    assert r.completed is True


def test_transicoes_de_status(repo):
    repo.ensure_control("000001", 1)
    assert repo.get_status("000001") == Status.PREENCHENDO
    # PREENCHENDO -> PREENCHIDO uma única vez
    assert repo.mark_preenchido("000001") is True
    assert repo.mark_preenchido("000001") is False
    assert repo.get_status("000001") == Status.PREENCHIDO
    # PREENCHIDO -> CONCLUIDO
    assert repo.mark_concluido("000001") is True
    assert repo.get_status("000001") == Status.CONCLUIDO


def test_expira_somente_se_preenchendo(repo):
    repo.ensure_control("000001", 1)
    assert repo.mark_expirado_if_preenchendo("000001") is True
    assert repo.get_status("000001") == Status.EXPIRADO

    # lote já concluído não expira
    repo.ensure_control("000002", 1)
    repo.mark_preenchido("000002")
    repo.mark_concluido("000002")
    assert repo.mark_expirado_if_preenchendo("000002") is False
    assert repo.get_status("000002") == Status.CONCLUIDO


def test_registro_de_controle_usa_placa_zero(repo):
    repo.ensure_control("000001", 1)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    item = table.get_item(Key={"PK": "000001", "SK": CONTROL_PLACA})["Item"]
    assert item["status"] == Status.PREENCHENDO
    assert int(item["lote_items"]) == 1
    assert int(item["itens_registrados"]) == 0


def test_timestamps_de_transicao_de_status(repo):
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    repo.ensure_control("000007", 1)

    item = table.get_item(Key={"PK": "000007", "SK": CONTROL_PLACA})["Item"]
    # epoch de PREENCHENDO gravado na criação
    assert "ts_PREENCHENDO" in item
    assert int(item["ts_PREENCHENDO"]) > 0

    repo.mark_preenchido("000007")
    repo.mark_concluido("000007")
    item = table.get_item(Key={"PK": "000007", "SK": CONTROL_PLACA})["Item"]
    # epochs das transições subsequentes também presentes
    assert "ts_PREENCHIDO" in item
    assert "ts_CONCLUIDO" in item
    # ordem temporal coerente
    assert int(item["ts_PREENCHENDO"]) <= int(item["ts_PREENCHIDO"]) <= int(item["ts_CONCLUIDO"])


def test_timestamp_expirado(repo):
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    repo.ensure_control("000008", 2)
    repo.mark_expirado_if_preenchendo("000008")
    item = table.get_item(Key={"PK": "000008", "SK": CONTROL_PLACA})["Item"]
    assert "ts_EXPIRADO" in item

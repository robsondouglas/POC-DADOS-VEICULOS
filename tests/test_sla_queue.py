"""Testes do SlaQueueClient (agendamento de SLA via SQS com delay)."""
import json
from unittest.mock import MagicMock

import pytest

from src.common.constants import SLA_SECONDS
from src.common.sla_queue import SlaQueueClient


@pytest.fixture
def sla_env(monkeypatch):
    monkeypatch.setenv("SLA_QUEUE_URL", "https://sqs/x/sla")


def test_schedule_sla_envia_mensagem_com_delay(sla_env):
    fake = MagicMock()
    SlaQueueClient(sqs=fake).schedule_sla("000001")

    _, kwargs = fake.send_message.call_args
    assert kwargs["QueueUrl"] == "https://sqs/x/sla"
    assert kwargs["DelaySeconds"] == SLA_SECONDS
    assert json.loads(kwargs["MessageBody"]) == {"lote": "000001"}


def test_delay_dentro_do_limite_da_sqs(sla_env):
    # SQS aceita DelaySeconds de 0 a 900; o SLA precisa caber nesse intervalo.
    assert 0 <= SLA_SECONDS <= 900

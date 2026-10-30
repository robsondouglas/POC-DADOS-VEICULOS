"""Testes do SchedulerClient (expressão de agendamento one-time)."""
import re
from datetime import datetime, timezone

from src.common.scheduler import SchedulerClient


def test_at_expression_formato_valido():
    expr = SchedulerClient._at_expression(30)
    # Formato esperado: at(yyyy-mm-ddThh:mm:ss)
    assert re.fullmatch(r"at\(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\)", expr)


def test_at_expression_no_futuro():
    expr = SchedulerClient._at_expression(30)
    ts = expr[len("at("):-1]
    fire_at = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    delta = (fire_at - datetime.now(timezone.utc)).total_seconds()
    # Deve estar ~30s à frente (com folga para latência do teste).
    assert 20 <= delta <= 40


def test_nao_usa_rate_em_segundos():
    # Garante que não regredimos para rate(.. seconds), que o Scheduler rejeita.
    assert "rate(" not in SchedulerClient._at_expression(30)

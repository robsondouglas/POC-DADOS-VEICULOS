"""Constantes e enums compartilhados da POC."""
from __future__ import annotations

# Placa reservada para o registro de controle do lote (SK).
CONTROL_PLACA = "0000000"

# SLA de processamento de um lote, em segundos.
SLA_SECONDS = 30

# TTL dos itens do DynamoDB, em segundos (1 dia).
TTL_SECONDS = 24 * 60 * 60


class Status:
    """Estados possíveis de um lote (registro de controle)."""

    PREENCHENDO = "PREENCHENDO"
    PREENCHIDO = "PREENCHIDO"
    CONCLUIDO = "CONCLUIDO"
    EXPIRADO = "EXPIRADO"


# Colunas da SOT (ordem canônica).
SOT_COLUMNS = ["lote", "placa", "ano_fabricacao", "modelo", "fabricante"]

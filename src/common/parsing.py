"""Parsing posicional das linhas dos arquivos de lote.

Layout (índices base-0, ambas as pontas inclusivas):
    LOTE           0-5    (6)
    LOTE-ITEMS     6-9    (4)
    PLACA          10-16  (7)
    ANO FABRICACAO 17-20  (4)
    MODELO         21-40  (20)
    FABRICANTE     41-60  (20)

A linha completa tem, portanto, 61 caracteres (índices 0..60).
Linhas malformadas são descartadas silenciosamente (retornam None).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

# (início inclusivo, fim exclusivo) para fatiamento Python.
_SLICES = {
    "lote": (0, 6),
    "lote_items": (6, 10),
    "placa": (10, 17),
    "ano_fabricacao": (17, 21),
    "modelo": (21, 41),
    "fabricante": (41, 61),
}

LINE_LENGTH = 61


@dataclass(frozen=True)
class VehicleRecord:
    """Um registro de veículo parseado de uma linha."""

    lote: str
    lote_items: int
    placa: str
    ano_fabricacao: int
    modelo: str
    fabricante: str


def _field(line: str, name: str) -> str:
    start, end = _SLICES[name]
    return line[start:end].strip()


def parse_line(line: str) -> VehicleRecord | None:
    """Converte uma linha em VehicleRecord.

    Retorna None (descarte silencioso) se a linha for malformada:
    comprimento insuficiente, campos obrigatórios vazios ou numéricos inválidos.
    """
    if line is None:
        return None

    # Remove quebras de linha, mas preserva espaços internos de padding.
    line = line.rstrip("\r\n")

    if len(line) < LINE_LENGTH:
        return None

    lote = _field(line, "lote")
    placa = _field(line, "placa")
    lote_items_raw = _field(line, "lote_items")
    ano_raw = _field(line, "ano_fabricacao")
    modelo = _field(line, "modelo")
    fabricante = _field(line, "fabricante")

    if not lote or not placa:
        return None

    if not lote_items_raw.isdigit() or not ano_raw.isdigit():
        return None

    lote_items = int(lote_items_raw)
    ano = int(ano_raw)

    if lote_items <= 0:
        return None
    if not (1900 <= ano <= 2100):
        return None

    return VehicleRecord(
        lote=lote,
        lote_items=lote_items,
        placa=placa,
        ano_fabricacao=ano,
        modelo=modelo,
        fabricante=fabricante,
    )


def parse_lines(lines: Iterable[str]) -> Iterator[VehicleRecord]:
    """Parseia um iterável de linhas, descartando as malformadas silenciosamente."""
    for line in lines:
        record = parse_line(line)
        if record is not None:
            yield record


def group_by_lote(records: Iterable[VehicleRecord]) -> dict[str, list[VehicleRecord]]:
    """Agrupa registros por ID de lote (um arquivo pode conter vários lotes)."""
    grouped: dict[str, list[VehicleRecord]] = {}
    for record in records:
        grouped.setdefault(record.lote, []).append(record)
    return grouped

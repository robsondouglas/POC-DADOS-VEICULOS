"""Testes do parser posicional."""
from src.common.parsing import (
    LINE_LENGTH,
    VehicleRecord,
    group_by_lote,
    parse_line,
    parse_lines,
)


def make_line(
    lote="000123",
    lote_items="0050",
    placa="ABC1234",
    ano="2020",
    modelo="GOL",
    fabricante="VW",
) -> str:
    """Monta uma linha posicional válida com padding à direita."""
    return (
        f"{lote:<6}"
        f"{lote_items:<4}"
        f"{placa:<7}"
        f"{ano:<4}"
        f"{modelo:<20}"
        f"{fabricante:<20}"
    )


def test_make_line_tem_comprimento_correto():
    assert len(make_line()) == LINE_LENGTH


def test_parse_line_valida():
    rec = parse_line(make_line())
    assert rec == VehicleRecord(
        lote="000123",
        lote_items=50,
        placa="ABC1234",
        ano_fabricacao=2020,
        modelo="GOL",
        fabricante="VW",
    )


def test_parse_line_remove_quebra_de_linha():
    assert parse_line(make_line() + "\n") is not None
    assert parse_line(make_line() + "\r\n") is not None


def test_parse_line_curta_e_descartada():
    assert parse_line("curta") is None


def test_parse_line_lote_items_nao_numerico_descartada():
    assert parse_line(make_line(lote_items="ABCD")) is None


def test_parse_line_ano_invalido_descartada():
    assert parse_line(make_line(ano="18AB")) is None


def test_parse_line_ano_fora_de_faixa_descartada():
    assert parse_line(make_line(ano="1800")) is None


def test_parse_line_lote_items_zero_descartada():
    assert parse_line(make_line(lote_items="0000")) is None


def test_parse_line_placa_vazia_descartada():
    assert parse_line(make_line(placa="       ")) is None


def test_parse_lines_descarta_malformadas_e_mantem_validas():
    linhas = [make_line(placa="AAA1111"), "lixo", make_line(placa="BBB2222")]
    recs = list(parse_lines(linhas))
    assert len(recs) == 2
    assert [r.placa for r in recs] == ["AAA1111", "BBB2222"]


def test_group_by_lote_separa_multiplos_lotes():
    recs = list(
        parse_lines(
            [
                make_line(lote="000001", placa="AAA1111"),
                make_line(lote="000002", placa="BBB2222"),
                make_line(lote="000001", placa="CCC3333"),
            ]
        )
    )
    grouped = group_by_lote(recs)
    assert set(grouped.keys()) == {"000001", "000002"}
    assert len(grouped["000001"]) == 2
    assert len(grouped["000002"]) == 1

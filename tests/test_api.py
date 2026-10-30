"""Testes da Lambda da API de visualização."""
import io
import json

import boto3
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from moto import mock_aws

SOT = "sot-test"


def _create_bucket(s3):
    s3.create_bucket(Bucket=SOT)


def _put_parquet(s3, lote, rows):
    cols = ["lote", "placa", "ano_fabricacao", "modelo", "fabricante"]
    table = pa.table({c: [r[c] for r in rows] for c in cols})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    s3.put_object(Bucket=SOT, Key=f"sot/lote={lote}/dados.parquet", Body=buf.getvalue())


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("BUCKET_SOT", SOT)


def test_lista_lotes(env):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        _create_bucket(s3)
        _put_parquet(s3, "000001", [dict(lote="000001", placa="AAA1111", ano_fabricacao=2020, modelo="GOL", fabricante="VW")])
        _put_parquet(s3, "000002", [dict(lote="000002", placa="BBB2222", ano_fabricacao=2021, modelo="UNO", fabricante="FIAT")])

        import src.api.handler as h

        resp = h.handler({"rawPath": "/api/lotes", "pathParameters": None})
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["lotes"] == ["000001", "000002"]


def test_lista_vazia(env):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        _create_bucket(s3)

        import src.api.handler as h

        resp = h.handler({"rawPath": "/api/lotes", "pathParameters": None})
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["lotes"] == []


def test_lote_inexistente_404(env):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        _create_bucket(s3)

        import src.api.handler as h

        resp = h.handler(
            {"rawPath": "/api/lotes/999999", "pathParameters": {"lote": "999999"}}
        )
        assert resp["statusCode"] == 404


def test_lote_invalido_400(env):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        _create_bucket(s3)

        import src.api.handler as h

        resp = h.handler(
            {"rawPath": "/api/lotes/..%2Fx", "pathParameters": {"lote": "../x"}}
        )
        assert resp["statusCode"] == 400


def test_detalhe_lote_ok(env):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        _create_bucket(s3)
        _put_parquet(
            s3,
            "000001",
            [dict(lote="000001", placa="AAA1111", ano_fabricacao=2020, modelo="GOL", fabricante="VW")],
        )

        import src.api.handler as h

        # Agora _read_lote baixa via boto3 e lê local (sem httpfs), então
        # roda de ponta a ponta contra o S3 mockado — sem precisar de patch.
        resp = h.handler(
            {"rawPath": "/api/lotes/000001", "pathParameters": {"lote": "000001"}}
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["lote"] == "000001"
        assert body["veiculos"][0]["placa"] == "AAA1111"
        assert body["veiculos"][0]["modelo"] == "GOL"


def test_duckdb_le_parquet_local(tmp_path):
    """Valida que a query DuckDB usada lê corretamente um Parquet (arquivo local)."""
    cols = ["lote", "placa", "ano_fabricacao", "modelo", "fabricante"]
    rows = [dict(lote="000001", placa="AAA1111", ano_fabricacao=2020, modelo="GOL", fabricante="VW")]
    table = pa.table({c: [r[c] for r in rows] for c in cols})
    path = tmp_path / "dados.parquet"
    pq.write_table(table, path)

    con = duckdb.connect()
    result = con.execute(
        "SELECT lote, placa, ano_fabricacao, modelo, fabricante FROM read_parquet(?)",
        [str(path)],
    ).fetchall()
    assert result == [("000001", "AAA1111", 2020, "GOL", "VW")]

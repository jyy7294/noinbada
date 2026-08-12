from fastapi.testclient import TestClient

from trzip.api import app


client = TestClient(app)


def test_hourly_api_exposes_provenance(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from trzip.hourly_store import backfill
    target = tmp_path / "hourly.sqlite3"
    monkeypatch.setenv("TRZIP_DB_PATH", str(target))
    backfill(datetime(2026, 5, 1, tzinfo=UTC), target)
    response = client.get("/api/v1/hourly/snapshot?at=2026-05-01T00:00:00Z")
    assert response.status_code == 200
    body = response.json()
    assert body["rows"]
    assert {row["provenance"] for row in body["rows"]} == {"generated"}


def test_intelligence_and_integration_routes_exist():
    assert client.get("/api/v1/intelligence?at=2026-07-15T00:00:00Z&hours=24").status_code == 200
    response = client.get("/api/v1/integrations")
    assert response.status_code == 200
    assert {"opendart", "pykrx"} <= response.json().keys()
    assert client.get("/api/v1/companies/pykrx-stock?stock_code=bad").status_code == 422
    assert client.get("/api/v1/companies/pykrx-stock?stock_code=bad").status_code == 422


def test_public_read_api_allows_frontend_cross_origin():
    response = client.options(
        "/api/v1/intelligence",
        headers={"Origin": "https://frontend.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"

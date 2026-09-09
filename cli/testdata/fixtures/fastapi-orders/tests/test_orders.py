"""Tests, read for their status-code assertions (rank 50)."""

from fastapi.testclient import TestClient

from orders_api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/healthz")
    assert response.status_code == 200


def test_get_missing_order():
    response = client.get("/api/v1/orders/999")
    assert response.status_code == 404


def test_create_order():
    response = client.post("/api/v1/orders", json={"customer_email": "a@b.c", "total_cents": 100})
    assert response.status_code == 201

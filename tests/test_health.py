"""tests/test_health.py — Tests for GET /health."""

def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_body_structure(client):
    data = client.get("/health").get_json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["database"] == "ok"

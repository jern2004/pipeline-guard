"""API tests. Each test starts with a fresh, empty database (see conftest.py)."""


def post_incident(client, **fields):
    payload = {"title": "Disk full", "description": "/var is at 100%"} | fields
    return client.post("/incidents", json=payload)


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_incident(client):
    response = post_incident(client, severity="high")

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["title"] == "Disk full"
    assert body["severity"] == "high"
    assert body["status"] == "open"
    assert body["created_at"] is not None
    assert body["resolved_at"] is None


def test_severity_defaults_to_medium(client):
    response = post_incident(client)

    assert response.json()["severity"] == "medium"


def test_invalid_severity_is_rejected(client):
    response = post_incident(client, severity="urgent")

    assert response.status_code == 422


def test_list_incidents(client):
    post_incident(client, title="First")
    post_incident(client, title="Second")

    response = client.get("/incidents")

    assert response.status_code == 200
    assert [incident["title"] for incident in response.json()] == ["First", "Second"]


def test_resolve_incident(client):
    incident_id = post_incident(client).json()["id"]

    response = client.patch(f"/incidents/{incident_id}/resolve")

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["resolved_at"] is not None


def test_resolve_is_idempotent(client):
    incident_id = post_incident(client).json()["id"]

    first = client.patch(f"/incidents/{incident_id}/resolve").json()
    second = client.patch(f"/incidents/{incident_id}/resolve").json()

    assert second["resolved_at"] == first["resolved_at"]


def test_resolve_unknown_incident_returns_404(client):
    response = client.patch("/incidents/999/resolve")

    assert response.status_code == 404

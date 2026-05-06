"""API integration tests for misc endpoints (health, metrics, static)."""


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["auth_enabled"] is True
    assert "redis" in data


def test_email_submission_template(client):
    resp = client.get("/api/email-submission-template")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "required_headers" in data
    assert "body_sections" in data


def test_metrics(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "snapshot_count_total" in resp.get_data(as_text=True)


def test_static_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")

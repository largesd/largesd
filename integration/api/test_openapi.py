"""Integration tests for OpenAPI/Swagger documentation."""


# ---------------------------------------------------------------------------
# Swagger UI & Spec
# ---------------------------------------------------------------------------
def test_swagger_ui_accessible(client):
    """Swagger UI should be served at /api/docs."""
    resp = client.get("/api/docs")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "swagger" in text.lower() or "openapi" in text.lower()


def test_apispec_json_returns_valid_spec(client):
    """The raw OpenAPI spec should be available and valid JSON."""
    resp = client.get("/apispec_1.json")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    spec = resp.get_json()
    assert spec.get("swagger") == "2.0"
    assert "paths" in spec
    assert "info" in spec
    assert spec["info"]["title"] == "Blind Debate Adjudicator API"


# ---------------------------------------------------------------------------
# Coverage checks
# ---------------------------------------------------------------------------
def _is_public_api_path(path: str) -> bool:
    return path.startswith("/api/") and path != "/api/docs"


def _flask_to_openapi_path(path: str) -> str:
    """Convert Flask path params <name> to OpenAPI {name}."""
    import re

    return re.sub(r"<([^>]+)>", r"{\1}", path)


def test_all_public_endpoints_documented(client):
    """Every registered /api/ route should appear in the OpenAPI spec."""
    registered = set()
    for rule in client.application.url_map.iter_rules():
        path = rule.rule
        if _is_public_api_path(path):
            registered.add(_flask_to_openapi_path(path))

    spec_resp = client.get("/apispec_1.json")
    assert spec_resp.status_code == 200
    spec = spec_resp.get_json()
    documented = set(spec.get("paths", {}).keys())

    missing = [p for p in registered if p not in documented]
    assert not missing, f"Missing OpenAPI docs for paths: {missing}"


def test_schemas_defined_for_post_endpoints(client):
    """POST endpoints should document request body parameters."""
    spec_resp = client.get("/apispec_1.json")
    assert spec_resp.status_code == 200
    spec = spec_resp.get_json()
    paths = spec.get("paths", {})

    post_paths = [p for p in paths if "post" in paths[p]]
    assert len(post_paths) > 0, "Expected at least one POST endpoint documented"

    for path in post_paths:
        post_spec = paths[path]["post"]
        params = post_spec.get("parameters", [])
        has_body = any(p.get("in") == "body" for p in params)
        # Not every POST has a body (e.g., simple actions), but key ones should
        if path in (
            "/api/auth/register",
            "/api/auth/login",
            "/api/debates",
            "/api/debate/posts",
            "/api/debate-proposals",
            "/api/governance/emergency-override",
            "/api/admin/appeals/{appeal_id}/resolve",
        ):
            assert has_body, f"POST {path} should document a body parameter"


def test_response_schemas_defined(client):
    """Documented endpoints should define response schemas."""
    spec_resp = client.get("/apispec_1.json")
    assert spec_resp.status_code == 200
    spec = spec_resp.get_json()
    paths = spec.get("paths", {})

    for path, methods in paths.items():
        for method, op in methods.items():
            if method == "parameters":
                continue
            responses = op.get("responses", {})
            assert any(
                k in responses for k in ("200", "201", "202")
            ), f"{method} {path} should document a success response"

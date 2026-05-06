"""Tests for Redis-backed rate limiting (Task 4.1)."""
import os
import importlib

import pytest

import backend.extensions


def _reload_app_v3():
    """Reload app_v3 module so create_app() picks up fresh env vars."""
    import backend.app_v3 as app_v3

    return importlib.reload(app_v3)


def test_health_includes_redis_status(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "redis" in data
    # In test conftest, ENABLE_RATE_LIMITER=false so Redis is not checked
    assert data["redis"] == "not_configured"


def test_redis_connected_uses_redis_storage(monkeypatch):
    """When Redis is reachable, storage_uri should be Redis and health reports connected."""
    redis = pytest.importorskip("redis")
    from flask_limiter import Limiter

    captured = {}
    original_init = Limiter.__init__

    def mock_limiter_init(self, *args, **kwargs):
        captured["storage_uri"] = kwargs.get("storage_uri")
        captured["strategy"] = kwargs.get("strategy")
        # Force memory:// to avoid real storage init, but capture intended URI
        kwargs["storage_uri"] = "memory://"
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(Limiter, "__init__", mock_limiter_init)

    class FakeRedis:
        def ping(self):
            return True

    monkeypatch.setattr(redis, "from_url", lambda url, **kwargs: FakeRedis())

    old_env = {
        k: os.environ.get(k)
        for k in ["ENABLE_RATE_LIMITER", "REDIS_URL", "ENV"]
    }
    os.environ["ENABLE_RATE_LIMITER"] = "true"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENV"] = "development"

    try:
        app_v3 = _reload_app_v3()
        app = app_v3.create_app()
        app.config["TESTING"] = True

        # Health should report redis connected
        with app.test_client() as client:
            resp = client.get("/api/health")
            data = resp.get_json()
            assert data["redis"] == "connected"

        # Extensions should show Redis connected
        assert backend.extensions.redis_connected is True
        # Limiter should have been configured with Redis URI
        assert captured["storage_uri"] == "redis://localhost:6379/0"
        assert captured["strategy"] == "fixed-window"
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_redis_unavailable_fallback_in_dev(monkeypatch):
    """In development, unreachable Redis falls back to memory://."""
    redis = pytest.importorskip("redis")
    from flask_limiter import Limiter

    captured = {}
    original_init = Limiter.__init__

    def mock_limiter_init(self, *args, **kwargs):
        captured["storage_uri"] = kwargs.get("storage_uri")
        kwargs["storage_uri"] = "memory://"
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(Limiter, "__init__", mock_limiter_init)

    def mock_from_url(url, **kwargs):
        raise ConnectionError("Redis down")

    monkeypatch.setattr(redis, "from_url", mock_from_url)

    old_env = {
        k: os.environ.get(k)
        for k in ["ENABLE_RATE_LIMITER", "REDIS_URL", "ENV"]
    }
    os.environ["ENABLE_RATE_LIMITER"] = "true"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENV"] = "development"

    try:
        app_v3 = _reload_app_v3()
        app = app_v3.create_app()
        app.config["TESTING"] = True

        with app.test_client() as client:
            resp = client.get("/api/health")
            data = resp.get_json()
            assert data["redis"] == "disconnected"

        assert backend.extensions.redis_connected is False
        assert captured["storage_uri"] == "memory://"
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_redis_unavailable_raises_in_production(monkeypatch):
    """In non-development environments, unreachable Redis should be fatal."""
    redis = pytest.importorskip("redis")
    from flask_limiter import Limiter

    original_init = Limiter.__init__

    def mock_limiter_init(self, *args, **kwargs):
        kwargs["storage_uri"] = "memory://"
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(Limiter, "__init__", mock_limiter_init)

    def mock_from_url(url, **kwargs):
        raise ConnectionError("Redis down")

    monkeypatch.setattr(redis, "from_url", mock_from_url)

    old_env = {
        k: os.environ.get(k)
        for k in ["ENABLE_RATE_LIMITER", "REDIS_URL", "ENV"]
    }
    os.environ["ENABLE_RATE_LIMITER"] = "true"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENV"] = "production"

    try:
        with pytest.raises(RuntimeError, match="FATAL: Redis required"):
            _reload_app_v3()
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_rate_limits_persist_across_app_restarts(monkeypatch):
    """Rate limit storage URI should remain Redis across app recreations."""
    redis = pytest.importorskip("redis")
    from flask_limiter import Limiter

    captured = {}
    original_init = Limiter.__init__

    def mock_limiter_init(self, *args, **kwargs):
        captured["storage_uri"] = kwargs.get("storage_uri")
        kwargs["storage_uri"] = "memory://"
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(Limiter, "__init__", mock_limiter_init)

    class FakeRedis:
        def ping(self):
            return True

    monkeypatch.setattr(redis, "from_url", lambda url, **kwargs: FakeRedis())

    old_env = {
        k: os.environ.get(k)
        for k in ["ENABLE_RATE_LIMITER", "REDIS_URL", "ENV", "DEBATE_DB_PATH"]
    }
    os.environ["ENABLE_RATE_LIMITER"] = "true"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENV"] = "development"
    db_path = old_env.get("DEBATE_DB_PATH") or os.environ.get(
        "DEBATE_DB_PATH", "data/debate_system.db"
    )
    os.environ["DEBATE_DB_PATH"] = db_path

    try:
        # First app instance
        app_v3_1 = _reload_app_v3()
        app1 = app_v3_1.create_app()
        app1.config["TESTING"] = True
        storage_uri_1 = captured["storage_uri"]

        # Second app instance (simulated restart)
        app_v3_2 = _reload_app_v3()
        app2 = app_v3_2.create_app()
        app2.config["TESTING"] = True
        storage_uri_2 = captured["storage_uri"]

        # Both should use Redis, proving state would persist if real Redis were backing them
        assert storage_uri_1 == "redis://localhost:6379/0"
        assert storage_uri_2 == "redis://localhost:6379/0"
        assert backend.extensions.redis_connected is True
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_multiple_workers_share_rate_limit_state(monkeypatch):
    """Multiple app instances should all point to the same Redis storage URI."""
    redis = pytest.importorskip("redis")
    from flask_limiter import Limiter

    captured = {}
    original_init = Limiter.__init__

    def mock_limiter_init(self, *args, **kwargs):
        captured["storage_uri"] = kwargs.get("storage_uri")
        kwargs["storage_uri"] = "memory://"
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(Limiter, "__init__", mock_limiter_init)

    class FakeRedis:
        def ping(self):
            return True

    monkeypatch.setattr(redis, "from_url", lambda url, **kwargs: FakeRedis())

    old_env = {
        k: os.environ.get(k)
        for k in ["ENABLE_RATE_LIMITER", "REDIS_URL", "ENV", "DEBATE_DB_PATH"]
    }
    os.environ["ENABLE_RATE_LIMITER"] = "true"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENV"] = "development"
    db_path = old_env.get("DEBATE_DB_PATH") or os.environ.get(
        "DEBATE_DB_PATH", "data/debate_system.db"
    )
    os.environ["DEBATE_DB_PATH"] = db_path

    try:
        # Worker 1
        app_v3_w1 = _reload_app_v3()
        worker1 = app_v3_w1.create_app()
        worker1.config["TESTING"] = True
        uri_1 = captured["storage_uri"]

        # Worker 2
        app_v3_w2 = _reload_app_v3()
        worker2 = app_v3_w2.create_app()
        worker2.config["TESTING"] = True
        uri_2 = captured["storage_uri"]

        # Both workers should use the same Redis-backed storage
        assert uri_1 == "redis://localhost:6379/0"
        assert uri_2 == "redis://localhost:6379/0"
        assert backend.extensions.redis_connected is True
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

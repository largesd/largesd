"""
Enhanced Flask API for Blind Debate Adjudicator v3
- Session-based debate management (no global state)
- Proper JWT authentication middleware
- Input validation
- Multi-debate support per user
- App factory + Blueprint decomposition
"""

import os
import warnings

import jwt  # noqa: F401
from flasgger import Swagger
from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

from backend import extensions
from backend.jobs.handlers import _handle_snapshot_job, _handle_verify_job
from backend.utils.logging import app_logger
from backend.utils.middleware import setup_middleware
from backend.utils.rate_limits import _should_exempt_default_rate_limits, apply_route_rate_limits

DB_PATH = os.getenv("DEBATE_DB_PATH", "data/debate_system.db")
ENV = os.getenv("ENV", "development")


def create_app(config_name="default"):
    """Flask application factory."""
    app = Flask(__name__, static_folder=None)

    # CORS configuration — restricted to explicit origin list
    origins = os.environ.get("ALLOWED_ORIGINS")
    configured_origins = [o.strip() for o in (origins or "").split(",") if o.strip()]

    if origins is None:
        warnings.warn("ALLOWED_ORIGINS not set; CORS disabled for safety", stacklevel=2)

    if not configured_origins:
        CORS(app, resources={r"/api/*": {"origins": []}})
    else:
        CORS(
            app,
            resources={
                r"/api/*": {
                    "origins": configured_origins,
                    "supports_credentials": True,
                    "allow_headers": ["Content-Type", "Authorization"],
                    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                }
            },
        )

    # Configuration
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    app.config["JWT_EXPIRATION_HOURS"] = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    # Rate limiting (disabled in testing mode)
    _enable_limiter = os.getenv("ENABLE_RATE_LIMITER", "true").lower() not in ("0", "false", "no")
    _redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    _storage_uri = "memory://"
    _redis_connected = None

    if _enable_limiter:
        try:
            import redis

            r = redis.from_url(_redis_url, socket_connect_timeout=2)
            r.ping()
            _storage_uri = _redis_url
            _redis_connected = True
            app_logger.info(f"Redis rate limiter connected: {_redis_url}")
        except Exception as e:
            _redis_connected = False
            app_logger.warning(f"Redis unavailable at {_redis_url}: {e}")
            if ENV != "development":
                raise RuntimeError(
                    f"FATAL: Redis required for rate limiting but unreachable at {_redis_url}: {e}"
                ) from e

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"] if _enable_limiter else [],
        default_limits_exempt_when=_should_exempt_default_rate_limits,
        storage_uri=_storage_uri,
        enabled=_enable_limiter,
        strategy="fixed-window",
    )

    # Security headers middleware (Flask-Talisman)
    Talisman(
        app,
        force_https=False,
        frame_options="DENY",
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        content_security_policy={
            "default-src": "'self'",
            "script-src": "'self'",
            "style-src": "'self'",
            "img-src": ["'self'", "data:", "https:"],
            "font-src": ["'self'", "https:"],
            "connect-src": "'self'",
            "frame-ancestors": "'none'",
            "base-uri": "'self'",
            "form-action": "'self'",
        },
        referrer_policy="strict-origin-when-cross-origin",
        feature_policy={"geolocation": "'none'", "microphone": "'none'", "camera": "'none'"},
    )

    # Environment validation on startup
    if ENV != "development":
        if app.config["SECRET_KEY"] == "dev-secret-key-change-in-production":
            raise RuntimeError(
                "FATAL: Default SECRET_KEY is not allowed in non-development environments. "
                "Set a strong SECRET_KEY environment variable."
            )
        if os.getenv("LLM_PROVIDER", "mock") != "mock" and not os.getenv("OPENROUTER_API_KEY"):
            raise RuntimeError(
                "FATAL: LLM_PROVIDER is set to a real provider but OPENROUTER_API_KEY is missing."
            )

    # Initialize shared extensions
    from backend.database_v3 import Database
    from backend.debate_engine_v2 import DebateEngineV2
    from backend.job_queue import JobQueue, JobWorker

    extensions.app = app
    extensions.db = Database(DB_PATH)
    extensions.db_path = DB_PATH
    extensions.env = ENV
    extensions.debate_engine = DebateEngineV2(
        db_path=DB_PATH,
        fact_check_mode=os.getenv("FACT_CHECKER_MODE", os.getenv("FACT_CHECK_MODE", "OFFLINE")),
        llm_provider=os.getenv("LLM_PROVIDER", "mock"),
        num_judges=int(os.getenv("NUM_JUDGES", "5")),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
    )
    extensions.current_runtime_profile = extensions.debate_engine.get_runtime_profile()
    extensions.job_queue = JobQueue(extensions.db)
    extensions.job_worker = JobWorker(
        extensions.job_queue,
        runtime_profile_id=extensions.current_runtime_profile["runtime_profile_id"],
    )
    extensions.limiter = limiter
    extensions.redis_connected = _redis_connected
    from backend.utils.validators import DEFAULT_MODERATION_SETTINGS

    extensions.default_moderation_settings = DEFAULT_MODERATION_SETTINGS

    # Async job queue handlers
    extensions.job_worker.register_handler("snapshot", _handle_snapshot_job)
    extensions.job_worker.register_handler("verify", _handle_verify_job)
    if os.environ.get("DISABLE_JOB_WORKER") != "1":
        extensions.job_worker.start()

    # Register blueprints
    from backend.routes import (
        admin_bp,
        api_bp,
        appeals_bp,
        auth_bp,
        debate_bp,
        dossier_bp,
        frame_bp,
        frame_petition_bp,
        governance_bp,
        judge_bp,
        posts_bp,
        proposal_bp,
        snapshot_bp,
        topic_bp,
    )

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(debate_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(topic_bp)
    app.register_blueprint(snapshot_bp)
    app.register_blueprint(dossier_bp)
    app.register_blueprint(proposal_bp)
    app.register_blueprint(frame_bp)
    app.register_blueprint(frame_petition_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(judge_bp)
    app.register_blueprint(governance_bp)
    app.register_blueprint(admin_bp)

    # OpenAPI / Swagger documentation
    Swagger(
        app,
        config={
            "swagger_ui": True,
            "specs_route": "/api/docs",
            "headers": [],
            "specs": [
                {
                    "endpoint": "apispec_1",
                    "route": "/apispec_1.json",
                    "rule_filter": lambda rule: rule.rule.startswith("/api/"),
                    "model_filter": lambda tag: True,
                }
            ],
            "static_url_path": "/flasgger_static",
        },
        template={
            "swagger": "2.0",
            "info": {
                "title": "Blind Debate Adjudicator API",
                "description": "API documentation for the debate_system backend.",
                "version": "3.0",
            },
            "basePath": "/",
        },
    )

    # Apply route-specific rate limits
    apply_route_rate_limits(app, limiter)

    # Middleware (CSRF, error handlers, request logging)
    setup_middleware(app)

    return app


# Legacy module-level exports for backwards compatibility with tests and WSGI
app = create_app()

debate_engine = extensions.debate_engine

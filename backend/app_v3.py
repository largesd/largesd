"""
Enhanced Flask API for Blind Debate Adjudicator v3
- Session-based debate management (no global state)
- Proper JWT authentication middleware
- Input validation
- Multi-debate support per user
- App factory + Blueprint decomposition
"""
import json
import logging
import os
import sys
import warnings
from datetime import datetime, timezone

from flask import Flask, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from backend.utils.middleware import setup_middleware
import jwt

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            'timestamp': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            'level': record.levelname, 'logger': record.name,
            'message': record.getMessage(), 'module': record.module,
            'funcName': record.funcName,
        }
        for attr in ('event_type', 'user_id', 'snapshot_id', 'request_id'):
            if hasattr(record, attr):
                log_obj[attr] = getattr(record, attr)
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JSONFormatter())
app_logger = logging.getLogger('debate_system')
app_logger.setLevel(logging.INFO)
app_logger.addHandler(_handler)
app_logger.propagate = False

DB_PATH = os.getenv("DEBATE_DB_PATH", "data/debate_system.db")
ENV = os.getenv('ENV', 'development')

def _should_exempt_default_rate_limits():
    """Apply the broad default limit only to mutating API requests."""
    return request.method in ("GET", "HEAD", "OPTIONS") or not request.path.startswith("/api/")


def _handle_snapshot_job(job_id: str, parameters: dict, queue):
    """Background handler for snapshot generation jobs."""
    from backend.github_publisher import get_publisher_from_env
    from backend.published_results import PublishedResultsBuilder
    _logger = logging.getLogger('debate_system')
    debate_id = parameters.get('debate_id')
    trigger_type = parameters.get('trigger_type', 'manual')
    request_id = parameters.get('request_id')
    queue.update_progress(job_id, 10)
    try:
        snapshot = extensions.debate_engine.generate_snapshot(
            debate_id=debate_id,
            trigger_type=trigger_type,
            request_id=request_id,
        )
        queue.update_progress(job_id, 90)
        publisher = get_publisher_from_env()
        if publisher:
            try:
                builder = PublishedResultsBuilder(db_path=DB_PATH, engine=extensions.debate_engine)
                bundle = builder.build_bundle(
                    debate_id=debate_id,
                    commit_message=f"Snapshot {snapshot['snapshot_id']} — {trigger_type}",
                )
                result = publisher.publish_json(
                    payload=bundle,
                    commit_message=bundle["commit_message"],
                )
                _logger.info(
                    f"Published to GitHub: {result.commit_sha}",
                    extra={'request_id': request_id}
                )
            except Exception as pub_err:
                _logger.error(
                    f"GitHub publish error: {pub_err}",
                    extra={'request_id': request_id}
                )
        queue.update_progress(job_id, 100)
        return {
            'snapshot_id': snapshot['snapshot_id'], 'timestamp': snapshot['timestamp'],
            'trigger_type': snapshot['trigger_type'], 'status': snapshot.get('status', 'valid'),
            'verdict': snapshot['verdict'], 'confidence': snapshot['confidence'],
        }
    except Exception as e:
        _logger.error(
            f"Async snapshot generation error: {str(e)}",
            extra={'request_id': request_id}
        )
        raise

def _handle_verify_job(job_id: str, parameters: dict, queue):
    """Background handler for nightly snapshot verification jobs."""
    _logger = logging.getLogger('debate_system')
    snapshot_id = parameters.get('snapshot_id')
    request_id = parameters.get('request_id')
    queue.update_progress(job_id, 10)
    try:
        result = extensions.debate_engine.verify_snapshot(snapshot_id)
        queue.update_progress(job_id, 100)
        _logger.info(
            f"Nightly verification complete for {snapshot_id}: verified={result.get('verified')}",
            extra={'request_id': request_id}
        )
        return result
    except Exception as e:
        _logger.error(
            f"Verification job failed for {snapshot_id}: {e}",
            extra={'request_id': request_id}
        )
        raise

def create_app(config_name="default"):
    """Flask application factory."""
    app = Flask(__name__, static_folder=None)

    # CORS configuration — restricted to explicit origin list
    origins = os.getenv("ALLOWED_ORIGINS", "")
    if not origins:
        warnings.warn("ALLOWED_ORIGINS not set; CORS disabled for safety")
        CORS(app, resources={r"/api/*": {"origins": []}})
    else:
        CORS(app, resources={
            r"/api/*": {
                "origins": [o.strip() for o in origins.split(",")],
                "supports_credentials": True,
                "allow_headers": ["Content-Type", "Authorization"],
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
            }
        })

    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['JWT_EXPIRATION_HOURS'] = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

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
            if ENV != 'development':
                raise RuntimeError(
                    f"FATAL: Redis required for rate limiting but unreachable at {_redis_url}: {e}"
                )

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
            "form-action": "'self'"
        },
        referrer_policy="strict-origin-when-cross-origin",
        feature_policy={
            "geolocation": "'none'",
            "microphone": "'none'",
            "camera": "'none'"
        }
    )

    # Environment validation on startup
    if ENV != 'development':
        if app.config['SECRET_KEY'] == 'dev-secret-key-change-in-production':
            raise RuntimeError(
                "FATAL: Default SECRET_KEY is not allowed in non-development environments. "
                "Set a strong SECRET_KEY environment variable."
            )
        if os.getenv('LLM_PROVIDER', 'mock') != 'mock' and not os.getenv('OPENROUTER_API_KEY'):
            raise RuntimeError(
                "FATAL: LLM_PROVIDER is set to a real provider but OPENROUTER_API_KEY is missing."
            )

    # Initialize shared extensions
    from backend import extensions
    from backend.debate_engine_v2 import DebateEngineV2
    from backend.database_v3 import Database
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
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY")
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
    extensions.job_worker.register_handler('snapshot', _handle_snapshot_job)
    extensions.job_worker.register_handler('verify', _handle_verify_job)
    if os.environ.get("DISABLE_JOB_WORKER") != "1":
        extensions.job_worker.start()

    # Register blueprints
    from backend.routes import (
        api_bp, auth_bp, debate_bp, topic_bp, snapshot_bp,
        dossier_bp, proposal_bp, governance_bp, admin_bp
    )
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(debate_bp)
    app.register_blueprint(topic_bp)
    app.register_blueprint(snapshot_bp)
    app.register_blueprint(dossier_bp)
    app.register_blueprint(proposal_bp)
    app.register_blueprint(governance_bp)
    app.register_blueprint(admin_bp)

    # Apply route-specific rate limits
    _RATE_LIMITS = {
        'debate.submit_post': "10 per hour; 30 per day",
        'snapshot.generate_snapshot': "5 per hour; 20 per day",
    }
    for endpoint, spec in _RATE_LIMITS.items():
        func = app.view_functions.get(endpoint)
        if func:
            app.view_functions[endpoint] = limiter.limit(spec)(func)

    # Middleware (CSRF, error handlers, request logging)
    setup_middleware(app)

    return app

# Legacy module-level exports for backwards compatibility with tests and WSGI
app = create_app()
from backend import extensions as _ext
debate_engine = _ext.debate_engine

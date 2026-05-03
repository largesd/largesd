"""
Enhanced Flask API for Blind Debate Adjudicator v3
- Session-based debate management (no global state)
- Proper JWT authentication middleware
- Input validation
- Multi-debate support per user
"""
import json
import os
import sys
import re
import uuid
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, Optional
from flask import Flask, jsonify, request, send_from_directory, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import jwt
from werkzeug.exceptions import BadRequest

# Structured JSON logging for production observability
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'funcName': record.funcName,
        }
        if hasattr(record, 'event_type'):
            log_obj['event_type'] = record.event_type
        if hasattr(record, 'user_id'):
            log_obj['user_id'] = record.user_id
        if hasattr(record, 'snapshot_id'):
            log_obj['snapshot_id'] = record.snapshot_id
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

# Configure app logger
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
app_logger = logging.getLogger('debate_system')
app_logger.setLevel(logging.INFO)
app_logger.addHandler(handler)
app_logger.propagate = False

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from debate_engine_v2 import DebateEngineV2
from database_v3 import Database
from modulation import ModulationEngine
from published_results import PublishedResultsBuilder
from github_publisher import get_publisher_from_env
from debate_proposal import parse_debate_proposal_payload
from email_submission_parser import EmailSubmissionParser
from lsd_v1_2 import AUDIT_SCHEMA_VERSION, formula_registry, frame_mode as get_frame_mode_flag
from job_queue import JobQueue, JobWorker, JobStatus

app = Flask(__name__, static_folder=None)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['JWT_EXPIRATION_HOURS'] = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max request size

# Rate limiting (disabled in testing mode)
_enable_limiter = os.getenv("ENABLE_RATE_LIMITER", "true").lower() not in ("0", "false", "no")


def _should_exempt_default_rate_limits():
    """Apply the broad default limit only to mutating API requests."""
    return request.method in ("GET", "HEAD", "OPTIONS") or not request.path.startswith("/api/")


limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"] if _enable_limiter else [],
    default_limits_exempt_when=_should_exempt_default_rate_limits,
    storage_uri="memory://",
    enabled=_enable_limiter,
)


@app.errorhandler(429)
def rate_limit_handler(e):
    """Return structured JSON for rate-limit errors instead of raw HTML."""
    retry_after = getattr(e, 'retry_after', None)
    response = jsonify({
        'error': 'Rate limit exceeded. Please slow down and retry.',
        'code': 'RATE_LIMITED',
        'retry_after': retry_after,
    })
    response.status_code = 429
    if retry_after:
        response.headers['Retry-After'] = str(retry_after)
    return response


# Environment validation on startup
ENV = os.getenv('ENV', 'development')
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

DB_PATH = os.getenv("DEBATE_DB_PATH", "data/debate_system.db")

# Initialize debate engine (shared, stateless)
debate_engine = DebateEngineV2(
    db_path=DB_PATH,
    fact_check_mode=os.getenv("FACT_CHECKER_MODE", os.getenv("FACT_CHECK_MODE", "OFFLINE")),
    llm_provider=os.getenv("LLM_PROVIDER", "mock"),
    num_judges=int(os.getenv("NUM_JUDGES", "5")),
    openrouter_api_key=os.getenv("OPENROUTER_API_KEY")
)
CURRENT_RUNTIME_PROFILE = debate_engine.get_runtime_profile()

# Security headers middleware
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    if ENV != 'development':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


# Database for user/session management
db = Database(DB_PATH)

# Async job queue for snapshot generation
job_queue = JobQueue(db)
job_worker = JobWorker(
    job_queue,
    runtime_profile_id=CURRENT_RUNTIME_PROFILE["runtime_profile_id"],
)

def _handle_snapshot_job(job_id: str, parameters: dict, queue):
    """Background handler for snapshot generation jobs."""
    debate_id = parameters.get('debate_id')
    trigger_type = parameters.get('trigger_type', 'manual')
    queue.update_progress(job_id, 10)
    try:
        snapshot = debate_engine.generate_snapshot(
            debate_id=debate_id,
            trigger_type=trigger_type
        )
        queue.update_progress(job_id, 90)
        # Optionally publish to GitHub
        publisher = get_publisher_from_env()
        if publisher:
            try:
                builder = PublishedResultsBuilder(db_path=DB_PATH, engine=debate_engine)
                bundle = builder.build_bundle(
                    debate_id=debate_id,
                    commit_message=f"Snapshot {snapshot['snapshot_id']} — {trigger_type}",
                )
                result = publisher.publish_json(
                    payload=bundle,
                    commit_message=bundle["commit_message"],
                )
                app.logger.info(f"Published to GitHub: {result.commit_sha}")
            except Exception as pub_err:
                app.logger.error(f"GitHub publish error: {pub_err}")
        queue.update_progress(job_id, 100)
        return {
            'snapshot_id': snapshot['snapshot_id'],
            'timestamp': snapshot['timestamp'],
            'trigger_type': snapshot['trigger_type'],
            'status': snapshot.get('status', 'valid'),
            'verdict': snapshot['verdict'],
            'confidence': snapshot['confidence'],
        }
    except Exception as e:
        app.logger.error(f"Async snapshot generation error: {str(e)}")
        raise

def _handle_verify_job(job_id: str, parameters: dict, queue):
    """Background handler for nightly snapshot verification jobs."""
    snapshot_id = parameters.get('snapshot_id')
    queue.update_progress(job_id, 10)
    try:
        result = debate_engine.verify_snapshot(snapshot_id)
        queue.update_progress(job_id, 100)
        app_logger.info(
            f"Nightly verification complete for {snapshot_id}: verified={result.get('verified')}"
        )
        return result
    except Exception as e:
        app_logger.error(f"Verification job failed for {snapshot_id}: {e}")
        raise

job_worker.register_handler('snapshot', _handle_snapshot_job)
job_worker.register_handler('verify', _handle_verify_job)
job_worker.start()

DEFAULT_MODERATION_SETTINGS = {
    "topic_requirements": {
        "required_keywords": [],
        "relevance_threshold": "moderate",
        "enforce_scope": True,
    },
    "toxicity_settings": {
        "sensitivity_level": 3,
        "block_personal_attacks": True,
        "block_hate_speech": True,
        "block_threats": True,
        "block_sexual_harassment": True,
        "block_mild_profanity": False,
    },
    "pii_settings": {
        "detect_email": True,
        "detect_phone": True,
        "detect_address": True,
        "detect_full_names": False,
        "detect_social_handles": False,
        "action": "block",
    },
    "spam_rate_limit_settings": {
        "min_length": 50,
        "max_length": 5000,
        "flood_threshold_per_hour": 10,
        "duplicate_detection": True,
        "rate_limiting": True,
    },
    "prompt_injection_settings": {
        "enabled": True,
        "block_markdown_hiding": True,
        "custom_patterns": [],
    },
}


# =============================================================================
# Validation Helpers
# =============================================================================

class ValidationError(Exception):
    pass


def validate_string(value, name, min_length=1, max_length=10000, required=True):
    """Validate a string field"""
    if value is None or value == '':
        if required:
            raise ValidationError(f"{name} is required")
        return None
    
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    
    value = value.strip()
    
    if len(value) < min_length:
        raise ValidationError(f"{name} must be at least {min_length} characters")
    
    if len(value) > max_length:
        raise ValidationError(f"{name} must be no more than {max_length} characters")
    
    return value


def validate_side(value, required=True):
    """Validate side field"""
    if value is None or value == '':
        if required:
            raise ValidationError("Side is required")
        return None
    
    value = str(value).upper().strip()
    if value not in ['FOR', 'AGAINST']:
        raise ValidationError("Side must be either 'FOR' or 'AGAINST'")
    
    return value


def validate_topic_id(value, required=True):
    """Validate topic_id field"""
    if value is None or value == '':
        if required:
            raise ValidationError("Topic is required")
        return None
    
    value = str(value).strip().lower()
    # Allow t1-t9 format or any alphanumeric
    if not re.match(r'^[a-z0-9_-]+$', value):
        raise ValidationError("Invalid topic ID format")
    
    return value


def sanitize_html(text):
    """Basic HTML sanitization"""
    if not text:
        return text
    # Remove script tags and event handlers
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'on\w+\s*=', '', text, flags=re.IGNORECASE)
    return text


# =============================================================================
# Authentication Middleware
# =============================================================================

def generate_token(user_id, email, display_name, is_admin=False):
    """Generate JWT token"""
    payload = {
        'user_id': user_id,
        'email': email,
        'display_name': display_name,
        'is_admin': bool(is_admin),
        'exp': datetime.utcnow() + timedelta(hours=app.config['JWT_EXPIRATION_HOURS']),
        'iat': datetime.utcnow(),
        'type': 'access'
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def decode_token(token):
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_auth_token():
    """Extract token from Authorization header"""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
    
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    
    return parts[1]


def login_required(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_auth_token()
        
        if not token:
            return jsonify({
                'error': 'Authentication required',
                'code': 'AUTH_REQUIRED'
            }), 401
        
        payload = decode_token(token)
        if not payload:
            return jsonify({
                'error': 'Invalid or expired token',
                'code': 'AUTH_INVALID'
            }), 401
        
        # Store user info in flask g object
        g.user = {
            'user_id': payload['user_id'],
            'email': payload['email'],
            'display_name': payload['display_name'],
            'is_admin': payload.get('is_admin', False)
        }
        
        return f(*args, **kwargs)
    
    return decorated_function


def optional_auth(f):
    """Decorator for optional authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_auth_token()
        g.user = None
        
        if token:
            payload = decode_token(token)
            if payload:
                g.user = {
                    'user_id': payload['user_id'],
                    'email': payload['email'],
                    'display_name': payload['display_name'],
                    'is_admin': payload.get('is_admin', False)
                }
        
        return f(*args, **kwargs)
    
    return decorated_function


# =============================================================================
# Admin Authorization + Moderation Template Validation
# =============================================================================

def get_admin_access_mode() -> str:
    """Return API admin access mode: open, authenticated, or restricted."""
    mode = (os.getenv('ADMIN_ACCESS_MODE') or 'restricted').strip().lower()
    return mode if mode in {'open', 'authenticated', 'restricted'} else 'restricted'


def parse_csv_env(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(',') if item.strip()}


def is_user_in_restricted_admin_list(user: Dict[str, str]) -> bool:
    allowed_emails = parse_csv_env(os.getenv('ADMIN_USER_EMAILS'))
    allowed_ids = parse_csv_env(os.getenv('ADMIN_USER_IDS'))
    user_email = (user.get('email') or '').lower()
    user_id = (user.get('user_id') or '').lower()
    return bool((allowed_emails and user_email in allowed_emails) or (allowed_ids and user_id in allowed_ids))


# Admin access startup warning
_admin_mode = get_admin_access_mode()
if _admin_mode != 'restricted':
    import warnings
    warnings.warn(
        f"ADMIN_ACCESS_MODE is set to '{_admin_mode}'. "
        "For production deployments, use 'restricted' with explicit ADMIN_USER_EMAILS or ADMIN_USER_IDS. "
        f"Current mode: {_admin_mode}",
        RuntimeWarning,
        stacklevel=2,
    )


def log_admin_action(action_type: str, description: str):
    """Log an admin action for audit trail."""
    user_id = (getattr(g, 'user', None) or {}).get('user_id', 'anonymous')
    app_logger.info(
        f"Admin action: {action_type} by {user_id}",
        extra={'event_type': 'admin_action', 'user_id': user_id}
    )


def admin_required(f):
    """Decorator for admin APIs with configurable access policy."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        mode = get_admin_access_mode()
        token = get_auth_token()
        g.user = None

        if token:
            payload = decode_token(token)
            if payload:
                g.user = {
                    'user_id': payload['user_id'],
                    'email': payload['email'],
                    'display_name': payload['display_name'],
                    'is_admin': payload.get('is_admin', False)
                }

        if mode == 'open':
            return f(*args, **kwargs)

        if not g.user:
            return jsonify({
                'error': 'Authentication required for admin actions',
                'code': 'AUTH_REQUIRED',
            }), 401

        if mode == 'restricted':
            # Restricted mode: explicit env allowlist ONLY.
            # The is_admin JWT flag is NOT sufficient on its own.
            if is_user_in_restricted_admin_list(g.user):
                return f(*args, **kwargs)
            return jsonify({
                'error': 'Admin access restricted to explicitly allowlisted accounts',
                'code': 'ADMIN_RESTRICTED',
                'detail': 'Contact the operator to be added to ADMIN_USER_EMAILS or ADMIN_USER_IDS',
            }), 403

        # authenticated mode: user must have is_admin flag in their JWT
        if g.user.get('is_admin'):
            return f(*args, **kwargs)

        return jsonify({
            'error': 'Admin access denied for this account',
            'code': 'ADMIN_FORBIDDEN',
        }), 403

    return decorated_function


def to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_list(value: Any, *, separator_pattern: str = r'[,;\n]') -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = re.split(separator_pattern, value)
    else:
        return []

    normalized = []
    seen = set()
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def resolve_template_id(raw_template_id: Optional[str]) -> str:
    aliases = {
        'standard': 'standard_civility',
        'standard_civility': 'standard_civility',
        'academic': 'strict',
        'strict': 'strict',
        'minimal': 'minimal',
        'custom': 'standard_civility',
    }
    template_id = aliases.get((raw_template_id or '').strip().lower(), raw_template_id or '')
    if template_id not in ModulationEngine.BUILTIN_TEMPLATES:
        return 'standard_civility'
    return template_id


def resolve_template_name(template_id: str, override_name: Optional[str] = None) -> str:
    if override_name and override_name.strip():
        return override_name.strip()
    config = ModulationEngine.BUILTIN_TEMPLATES.get(template_id, {})
    return config.get('name', 'Custom Moderation Template')


def validate_version_field(value: Any, default_value: str = '1.0.0') -> str:
    raw = str(value).strip() if value is not None else ''
    version = raw or default_value
    if len(version) > 40 or not re.match(r'^[A-Za-z0-9._-]+$', version):
        raise ValidationError("Version must use letters, numbers, dots, underscores, or dashes")
    return version


def merge_dict(defaults: Dict[str, Any], incoming: Any) -> Dict[str, Any]:
    merged = dict(defaults)
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            merged[key] = value
    return merged


def normalize_moderation_template_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    base_template_id = resolve_template_id(payload.get('base_template_id'))
    version = validate_version_field(payload.get('version'))
    template_name = resolve_template_name(base_template_id, payload.get('template_name'))
    notes = validate_string(payload.get('notes'), 'Notes', min_length=0, max_length=500, required=False) or ''

    topic_raw = merge_dict(DEFAULT_MODERATION_SETTINGS['topic_requirements'], payload.get('topic_requirements'))
    threshold = str(topic_raw.get('relevance_threshold', 'moderate')).strip().lower()
    if threshold not in {'strict', 'moderate', 'permissive'}:
        threshold = 'moderate'
    topic_requirements = {
        'required_keywords': normalize_list(topic_raw.get('required_keywords'))[:50],
        'relevance_threshold': threshold,
        'enforce_scope': to_bool(topic_raw.get('enforce_scope'), True),
    }

    toxicity_raw = merge_dict(DEFAULT_MODERATION_SETTINGS['toxicity_settings'], payload.get('toxicity_settings'))
    sensitivity_level = to_int(toxicity_raw.get('sensitivity_level', 3), 3)
    sensitivity_level = max(1, min(5, sensitivity_level))
    toxicity_settings = {
        'sensitivity_level': sensitivity_level,
        'block_personal_attacks': to_bool(toxicity_raw.get('block_personal_attacks'), True),
        'block_hate_speech': to_bool(toxicity_raw.get('block_hate_speech'), True),
        'block_threats': to_bool(toxicity_raw.get('block_threats'), True),
        'block_sexual_harassment': to_bool(toxicity_raw.get('block_sexual_harassment'), True),
        'block_mild_profanity': to_bool(toxicity_raw.get('block_mild_profanity'), False),
    }

    pii_raw = merge_dict(DEFAULT_MODERATION_SETTINGS['pii_settings'], payload.get('pii_settings'))
    pii_action = str(pii_raw.get('action', 'block')).strip().lower()
    if pii_action not in {'block', 'redact', 'flag'}:
        pii_action = 'block'
    pii_settings = {
        'detect_email': to_bool(pii_raw.get('detect_email'), True),
        'detect_phone': to_bool(pii_raw.get('detect_phone'), True),
        'detect_address': to_bool(pii_raw.get('detect_address'), True),
        'detect_full_names': to_bool(pii_raw.get('detect_full_names'), False),
        'detect_social_handles': to_bool(pii_raw.get('detect_social_handles'), False),
        'action': pii_action,
    }

    spam_raw = merge_dict(
        DEFAULT_MODERATION_SETTINGS['spam_rate_limit_settings'],
        payload.get('spam_rate_limit_settings'),
    )
    min_length = max(0, min(20000, to_int(spam_raw.get('min_length', 50), 50)))
    max_length = max(min_length, min(50000, to_int(spam_raw.get('max_length', 5000), 5000)))
    flood_threshold = max(1, min(5000, to_int(spam_raw.get('flood_threshold_per_hour', 10), 10)))
    spam_rate_limit_settings = {
        'min_length': min_length,
        'max_length': max_length,
        'flood_threshold_per_hour': flood_threshold,
        'duplicate_detection': to_bool(spam_raw.get('duplicate_detection'), True),
        'rate_limiting': to_bool(spam_raw.get('rate_limiting'), True),
    }

    prompt_raw = merge_dict(
        DEFAULT_MODERATION_SETTINGS['prompt_injection_settings'],
        payload.get('prompt_injection_settings'),
    )
    prompt_injection_settings = {
        'enabled': to_bool(prompt_raw.get('enabled'), True),
        'block_markdown_hiding': to_bool(prompt_raw.get('block_markdown_hiding'), True),
        'custom_patterns': normalize_list(prompt_raw.get('custom_patterns'))[:50],
    }

    return {
        'base_template_id': base_template_id,
        'template_name': template_name,
        'version': version,
        'notes': notes,
        'topic_requirements': topic_requirements,
        'toxicity_settings': toxicity_settings,
        'pii_settings': pii_settings,
        'spam_rate_limit_settings': spam_rate_limit_settings,
        'prompt_injection_settings': prompt_injection_settings,
    }


# =============================================================================
# Session-based Debate Management
# =============================================================================

def get_session_debate_id():
    """Get debate ID from session or query params"""
    # Check query params first (allows sharing links)
    debate_id = request.args.get('debate_id')
    if debate_id:
        return debate_id
    
    # Check header
    debate_id = request.headers.get('X-Debate-ID')
    if debate_id:
        return debate_id
    
    # Check user's active debate from database
    user = getattr(g, 'user', None)
    if user:
        user_prefs = db.get_user_preferences(user['user_id'])
        if user_prefs and user_prefs.get('active_debate_id'):
            return user_prefs['active_debate_id']
    
    return None


def set_session_debate(debate_id):
    """Set active debate for user"""
    user = getattr(g, 'user', None)
    if user:
        db.set_user_preference(user['user_id'], 'active_debate_id', debate_id)


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(ValidationError)
def handle_validation_error(error):
    return jsonify({'error': str(error), 'code': 'VALIDATION_ERROR'}), 400


@app.errorhandler(BadRequest)
def handle_bad_request(error):
    return jsonify({'error': 'Invalid request format', 'code': 'BAD_REQUEST'}), 400


@app.errorhandler(404)
def handle_not_found(error):
    return jsonify({'error': 'Not found', 'code': 'NOT_FOUND'}), 404


@app.errorhandler(500)
def handle_server_error(error):
    return jsonify({'error': 'Internal server error', 'code': 'SERVER_ERROR'}), 500


# =============================================================================
# API Routes
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "version": "3.0",
        "auth_enabled": True,
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/email-submission-template', methods=['GET'])
def get_email_submission_template():
    """Return the canonical email body template and expected fields."""
    return jsonify({
        "version": "BDA Submission v1",
        "required_headers": [
            "Debate-ID", "Resolution", "Submission-ID",
            "Submitted-At", "Position", "Topic-Area"
        ],
        "body_sections": ["Facts", "Inference", "Counter-Arguments"],
        "example": EmailSubmissionParser().build_email_body(
            debate_id="DEBATE_ID",
            resolution="RESOLUTION_TEXT",
            side="FOR",
            topic_id="t1",
            facts="Your facts here.",
            inference="Your inference here.",
            counter_arguments="Optional counter-arguments."
        ),
    })


@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register new user"""
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")
    
    email = validate_string(data.get('email'), 'Email', min_length=5, max_length=255)
    password = validate_string(data.get('password'), 'Password', min_length=8, max_length=128)
    display_name = validate_string(data.get('display_name'), 'Display name', min_length=2, max_length=100)
    
    # Validate email format
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        raise ValidationError("Invalid email format")
    
    # Check if email exists
    existing = db.get_user_by_email(email)
    if existing:
        return jsonify({'error': 'Email already registered', 'code': 'EMAIL_EXISTS'}), 409
    
    # Create user
    user = db.create_user(email, password, display_name)
    
    # Generate token
    token = generate_token(user['user_id'], user['email'], user['display_name'], user.get('is_admin', False))
    
    return jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'display_name': user['display_name'],
        'is_admin': user.get('is_admin', False),
        'access_token': token
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login user"""
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")
    
    email = validate_string(data.get('email'), 'Email')
    password = validate_string(data.get('password'), 'Password')
    
    # Verify credentials
    user = db.verify_user(email, password)
    if not user:
        return jsonify({'error': 'Invalid credentials', 'code': 'INVALID_CREDENTIALS'}), 401
    
    # Update last login
    db.update_last_login(user['user_id'])
    
    # Generate token
    token = generate_token(user['user_id'], user['email'], user['display_name'], user.get('is_admin', False))
    
    return jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'display_name': user['display_name'],
        'is_admin': user.get('is_admin', False),
        'access_token': token
    })


@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """Logout user (client should discard token)"""
    # In a more complex system, we might blacklist the token
    return jsonify({'message': 'Logged out successfully'})


@app.route('/api/auth/me', methods=['GET'])
@login_required
def get_current_user():
    """Get current user info"""
    return jsonify(g.user)


# =============================================================================
# Admin Moderation Template Routes
# =============================================================================

@app.route('/api/admin/moderation-template/current', methods=['GET'])
@admin_required
def get_current_admin_moderation_template():
    """Get the active moderation template and live moderation outcomes."""
    template = db.get_active_moderation_template()
    debate_id = get_session_debate_id()
    moderation_outcomes = db.get_moderation_outcome_summary(debate_id=debate_id)
    latest_snapshot = db.get_latest_snapshot(debate_id) if debate_id else db.get_latest_snapshot_any()
    suppression_policy = {}
    if latest_snapshot:
        suppression_policy = json.loads(latest_snapshot.get('suppression_policy_json', '{}') or '{}')

    return jsonify({
        'template': template,
        'moderation_outcomes': moderation_outcomes,
        'suppression_policy': suppression_policy or {
            'k': 5,
            'affected_buckets': [],
            'affected_bucket_count': 0,
        },
        'available_bases': ModulationEngine.list_builtin_templates(),
        'admin_access_mode': get_admin_access_mode(),
    })


@app.route('/api/admin/moderation-template/history', methods=['GET'])
@admin_required
def get_admin_moderation_template_history():
    """List moderation template drafts/applied versions."""
    limit = request.args.get('limit', 50, type=int)
    limit = max(1, min(limit, 200))
    history = db.get_moderation_template_history(limit=limit)
    return jsonify({
        'history': history,
        'count': len(history),
        'admin_access_mode': get_admin_access_mode(),
    })


@app.route('/api/admin/moderation-template/draft', methods=['POST'])
@admin_required
def save_admin_moderation_template_draft():
    """Save moderation settings as a versioned draft template."""
    data = request.get_json() or {}
    payload = normalize_moderation_template_payload(data)
    author_user_id = (getattr(g, 'user', None) or {}).get('user_id')

    draft = db.create_moderation_template_version(
        base_template_id=payload['base_template_id'],
        template_name=payload['template_name'],
        version=payload['version'],
        status='draft',
        topic_requirements=payload['topic_requirements'],
        toxicity_settings=payload['toxicity_settings'],
        pii_settings=payload['pii_settings'],
        spam_rate_limit_settings=payload['spam_rate_limit_settings'],
        prompt_injection_settings=payload['prompt_injection_settings'],
        author_user_id=author_user_id,
        notes=payload['notes'],
    )

    return jsonify({
        'message': 'Draft template saved',
        'template': draft,
    }), 201


@app.route('/api/admin/moderation-template/apply', methods=['POST'])
@admin_required
def apply_admin_moderation_template():
    """Apply a moderation template version and update the active pointer."""
    data = request.get_json() or {}
    author_user_id = (getattr(g, 'user', None) or {}).get('user_id')
    template_record_id = (data.get('template_record_id') or '').strip()

    if template_record_id:
        applied = db.activate_moderation_template(
            template_record_id,
            author_user_id=author_user_id,
        )
        if not applied:
            return jsonify({'error': 'Template record not found'}), 404
    else:
        payload = normalize_moderation_template_payload(data)
        applied = db.create_moderation_template_version(
            base_template_id=payload['base_template_id'],
            template_name=payload['template_name'],
            version=payload['version'],
            status='active',
            topic_requirements=payload['topic_requirements'],
            toxicity_settings=payload['toxicity_settings'],
            pii_settings=payload['pii_settings'],
            spam_rate_limit_settings=payload['spam_rate_limit_settings'],
            prompt_injection_settings=payload['prompt_injection_settings'],
            author_user_id=author_user_id,
            notes=payload['notes'],
        )

    debate_engine.refresh_active_modulation_template(force=True)
    moderation_outcomes = db.get_moderation_outcome_summary(debate_id=get_session_debate_id())

    return jsonify({
        'message': 'Template applied and set active',
        'template': applied,
        'moderation_outcomes': moderation_outcomes,
    })


# =============================================================================
# Debate Routes
# =============================================================================

@app.route('/api/debates', methods=['GET'])
@optional_auth
def list_debates():
    """List debates accessible to user"""
    if g.user:
        debates = db.get_debates_by_user(g.user['user_id'])
    else:
        # For non-authenticated users, return public debates or empty
        debates = db.get_public_debates()
    
    return jsonify({
        'debates': [
            {
                'debate_id': d['debate_id'],
                'resolution': d['resolution'],
                'scope': d['scope'][:200] + '...' if len(d['scope']) > 200 else d['scope'],
                'created_at': d['created_at'],
                'has_snapshot': d.get('has_snapshot', False)
            }
            for d in debates
        ]
    })


@app.route('/api/debates', methods=['POST'])
@admin_required
def create_debate():
    """Create a new debate directly (admin only)."""
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")
    
    resolution = validate_string(
        data.get('resolution'), 
        'Resolution', 
        min_length=10, 
        max_length=500
    )
    resolution = sanitize_html(resolution)
    
    scope = validate_string(
        data.get('scope'), 
        'Scope', 
        min_length=10, 
        max_length=2000
    )
    scope = sanitize_html(scope)
    
    # Create the debate through the shared engine, then persist ownership
    # through the v3 database layer for user-specific listing/access.
    debate = debate_engine.create_debate(
        resolution=resolution,
        scope=scope
    )
    debate['user_id'] = g.user['user_id']
    db.save_debate(debate)
    
    # Set as user's active debate
    set_session_debate(debate['debate_id'])
    
    return jsonify({
        'debate_id': debate['debate_id'],
        'resolution': debate['resolution'],
        'scope': debate['scope'],
        'created_at': debate['created_at'],
        'creator': g.user['display_name']
    }), 201


@app.route('/api/debate', methods=['GET'])
@optional_auth
def get_debate():
    """Get current/active debate"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        # No active debate
        return jsonify({
            'debate_id': None,
            'resolution': None,
            'scope': None,
            'created_at': None,
            'current_snapshot_id': None,
            'has_debate': False
        })
    
    debate = db.get_debate(debate_id)
    
    if not debate:
        return jsonify({
            'error': 'Debate not found',
            'code': 'DEBATE_NOT_FOUND'
        }), 404
    
    # Check access (if debate is private)
    if debate.get('is_private') and debate.get('user_id') != (g.user['user_id'] if g.user else None):
        return jsonify({
            'error': 'Access denied',
            'code': 'ACCESS_DENIED'
        }), 403
    
    return jsonify({
        'debate_id': debate['debate_id'],
        'resolution': debate['resolution'],
        'scope': debate['scope'],
        'created_at': debate['created_at'],
        'current_snapshot_id': debate.get('current_snapshot_id'),
        'has_debate': True,
        'is_owner': g.user and debate.get('user_id') == g.user['user_id']
    })


@app.route('/api/debate/<debate_id>', methods=['GET'])
@optional_auth
def get_debate_by_id(debate_id):
    """Get specific debate by ID"""
    if not debate_id or not re.match(r'^[a-zA-Z0-9_-]+$', debate_id):
        raise ValidationError("Invalid debate ID")
    
    debate = db.get_debate(debate_id)
    
    if not debate:
        return jsonify({'error': 'Debate not found'}), 404
    
    # Set as active if user is authenticated
    if g.user:
        set_session_debate(debate_id)
    
    return jsonify({
        'debate_id': debate['debate_id'],
        'resolution': debate['resolution'],
        'scope': debate['scope'],
        'created_at': debate['created_at'],
        'current_snapshot_id': debate.get('current_snapshot_id'),
        'has_debate': True
    })


@app.route('/api/debate/<debate_id>/activate', methods=['POST'])
@login_required
def activate_debate(debate_id):
    """Set a debate as the user's active debate"""
    if not debate_id or not re.match(r'^[a-zA-Z0-9_-]+$', debate_id):
        raise ValidationError("Invalid debate ID")
    
    debate = db.get_debate(debate_id)
    if not debate:
        return jsonify({'error': 'Debate not found'}), 404
    
    set_session_debate(debate_id)
    
    return jsonify({
        'message': 'Debate activated',
        'debate_id': debate_id
    })


# =============================================================================
# Debate Proposal Routes
# =============================================================================

@app.route('/api/debate-proposals', methods=['POST'])
@login_required
def submit_debate_proposal():
    """Submit a new debate proposal (regular users)."""
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")

    proposal, missing_fields = parse_debate_proposal_payload(data)
    if missing_fields:
        raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")

    proposal_id = f"prop_{uuid.uuid4().hex[:10]}"
    now = datetime.now().isoformat()

    db.save_debate_proposal({
        'proposal_id': proposal_id,
        'proposer_user_id': g.user['user_id'],
        'motion': proposal['motion'],
        'moderation_criteria': proposal['moderation_criteria'],
        'debate_frame': proposal.get('debate_frame', ''),
        'frame_payload_json': proposal.get('active_frame', {}),
        'status': 'pending',
        'decision_reason': None,
        'reviewer_user_id': None,
        'reviewed_at': None,
        'accepted_debate_id': None,
        'created_at': now,
        'updated_at': now,
    })

    return jsonify({
        'proposal_id': proposal_id,
        'status': 'pending',
        'message': 'Proposal submitted for review'
    }), 201


@app.route('/api/debate-proposals/mine', methods=['GET'])
@login_required
def get_my_proposals():
    """Get current user's debate proposals."""
    proposals = db.get_debate_proposals_by_user(g.user['user_id'])
    return jsonify({
        'proposals': [
            {
                'proposal_id': p['proposal_id'],
                'motion': p['motion'],
                'status': p['status'],
                'decision_reason': p.get('decision_reason'),
                'accepted_debate_id': p.get('accepted_debate_id'),
                'created_at': p['created_at'],
                'reviewed_at': p.get('reviewed_at'),
            }
            for p in proposals
        ]
    })


@app.route('/api/admin/debate-proposals', methods=['GET'])
@admin_required
def list_proposal_queue():
    """Admin queue: list debate proposals, filterable by status."""
    status = request.args.get('status')
    if status and status not in {'pending', 'accepted', 'rejected'}:
        raise ValidationError("Status must be one of: pending, accepted, rejected")

    proposals = db.get_debate_proposals_by_status(status=status, limit=200)
    return jsonify({
        'proposals': [
            {
                'proposal_id': p['proposal_id'],
                'proposer_user_id': p['proposer_user_id'],
                'motion': p['motion'],
                'moderation_criteria': p['moderation_criteria'],
                'debate_frame': p.get('debate_frame', ''),
                'frame_payload_json': p.get('frame_payload_json', {}),
                'status': p['status'],
                'decision_reason': p.get('decision_reason'),
                'reviewer_user_id': p.get('reviewer_user_id'),
                'reviewed_at': p.get('reviewed_at'),
                'accepted_debate_id': p.get('accepted_debate_id'),
                'created_at': p['created_at'],
            }
            for p in proposals
        ]
    })


@app.route('/api/admin/debate-proposals/<proposal_id>/accept', methods=['POST'])
@admin_required
def accept_proposal(proposal_id):
    """Accept a debate proposal and create the debate."""
    proposal = db.get_debate_proposal(proposal_id)
    if not proposal:
        return jsonify({'error': 'Proposal not found'}), 404
    if proposal['status'] != 'pending':
        return jsonify({'error': f"Proposal is already {proposal['status']}"}), 409

    payload = {
        'motion': proposal['motion'],
        'moderation_criteria': proposal['moderation_criteria'],
        'debate_frame': proposal.get('debate_frame', ''),
        'frame': proposal.get('frame_payload_json', {}),
    }

    debate = debate_engine.create_debate(payload, user_id=proposal['proposer_user_id'])
    db.save_debate(debate)

    db.update_debate_proposal_status(
        proposal_id,
        status='accepted',
        reviewer_user_id=g.user['user_id'],
        accepted_debate_id=debate['debate_id'],
    )

    db.set_user_preference(
        proposal['proposer_user_id'],
        'active_debate_id',
        debate['debate_id'],
    )
    set_session_debate(debate['debate_id'])

    return jsonify({
        'message': 'Proposal accepted and debate created',
        'debate_id': debate['debate_id'],
        'proposal_id': proposal_id,
    })


@app.route('/api/admin/debate-proposals/<proposal_id>/reject', methods=['POST'])
@admin_required
def reject_proposal(proposal_id):
    """Reject a debate proposal with reason."""
    proposal = db.get_debate_proposal(proposal_id)
    if not proposal:
        return jsonify({'error': 'Proposal not found'}), 404
    if proposal['status'] != 'pending':
        return jsonify({'error': f"Proposal is already {proposal['status']}"}), 409

    data = request.get_json() or {}
    reason = validate_string(data.get('reason'), 'Reason', min_length=5, max_length=1000)
    reason = sanitize_html(reason)

    db.update_debate_proposal_status(
        proposal_id,
        status='rejected',
        decision_reason=reason,
        reviewer_user_id=g.user['user_id'],
    )

    return jsonify({
        'message': 'Proposal rejected',
        'proposal_id': proposal_id,
        'reason': reason,
    })


# =============================================================================
# Post Routes
# =============================================================================

@app.route('/api/debate/posts', methods=['POST'])
@login_required
@limiter.limit("10 per hour; 30 per day")
def submit_post():
    """Submit a new post"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")
    
    # Validate inputs
    side = validate_side(data.get('side'))
    topic_id = validate_topic_id(data.get('topic_id'))
    facts = validate_string(data.get('facts'), 'Facts', min_length=5, max_length=5000)
    inference = validate_string(data.get('inference'), 'Inference', min_length=5, max_length=2000)
    counter_arguments = data.get('counter_arguments', '')
    
    if counter_arguments:
        counter_arguments = validate_string(
            counter_arguments, 
            'Counter-arguments', 
            required=False, 
            max_length=2000
        )
    
    # Sanitize
    facts = sanitize_html(facts)
    inference = sanitize_html(inference)
    counter_arguments = sanitize_html(counter_arguments)
    
    # Submit post through the shared engine, then attach the submitting user
    # so the v3 database layer preserves authorship metadata.
    post = debate_engine.submit_post(
        debate_id=debate_id,
        side=side,
        topic_id=topic_id,
        facts=facts,
        inference=inference,
        counter_arguments=counter_arguments
    )
    post['user_id'] = g.user['user_id']
    db.save_post(post)
    
    return jsonify({
        'post_id': post['post_id'],
        'side': post['side'],
        'topic_id': post.get('topic_id'),
        'modulation_outcome': post['modulation_outcome'],
        'block_reason': post.get('block_reason'),
        'timestamp': post['timestamp']
    })


@app.route('/api/debate/posts', methods=['GET'])
@optional_auth
def get_posts():
    """Get posts for current debate"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    posts = db.get_posts_by_debate(debate_id)
    
    return jsonify({
        'posts': [
            {
                'post_id': p['post_id'],
                'side': p['side'],
                'topic_id': p['topic_id'],
                'modulation_outcome': p['modulation_outcome'],
                'block_reason': p.get('block_reason'),
                'timestamp': p['timestamp']
            }
            for p in posts
        ]
    })


# =============================================================================
# Snapshot Routes
# =============================================================================

@app.route('/api/debate/snapshot', methods=['POST'])
@login_required
@limiter.limit("5 per hour; 20 per day")
def generate_snapshot():
    """Enqueue a new snapshot generation job and return job_id for polling."""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    data = request.get_json() or {}
    trigger_type = validate_string(
        data.get('trigger_type', 'manual'),
        'Trigger type',
        required=False,
        max_length=50
    )
    
    # Validate trigger type
    valid_triggers = ['manual', 'activity', 'time', 'scheduled']
    if trigger_type not in valid_triggers:
        raise ValidationError(f"Trigger type must be one of: {', '.join(valid_triggers)}")
    
    # Ownership check
    debate = db.get_debate(debate_id)
    if not debate:
        return jsonify({'error': 'Debate not found'}), 404
    if debate.get('is_private') and debate.get('user_id') != g.user['user_id']:
        return jsonify({'error': 'Access denied'}), 403
    
    job_id = job_queue.create_job(
        'snapshot',
        {
            'debate_id': debate_id,
            'trigger_type': trigger_type,
            'user_id': g.user['user_id'],
        },
        runtime_profile_id=CURRENT_RUNTIME_PROFILE["runtime_profile_id"],
    )
    
    return jsonify({
        'job_id': job_id,
        'status': 'queued',
        'message': 'Snapshot generation queued. Poll /api/debate/snapshot-jobs/<job_id> for status.'
    }), 202


@app.route('/api/debate/snapshot-jobs/<job_id>', methods=['GET'])
@login_required
def get_snapshot_job(job_id):
    """Poll snapshot job status and result."""
    job = job_queue.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Ownership check: only the submitter or an admin can view
    job_user_id = (job.parameters or {}).get('user_id')
    if job_user_id and g.user['user_id'] != job_user_id:
        mode = get_admin_access_mode()
        if mode != 'open' and not is_user_in_restricted_admin_list(g.user):
            return jsonify({'error': 'Access denied'}), 403
    
    result = job_queue.to_public_dict(job)
    # If completed, enrich with snapshot summary
    if job.status == JobStatus.COMPLETED and job.result:
        result['snapshot_summary'] = {
            'snapshot_id': job.result.get('snapshot_id'),
            'verdict': job.result.get('verdict'),
            'confidence': job.result.get('confidence'),
            'status': job.result.get('status'),
        }
    return jsonify(result)


@app.route('/api/debate/snapshot', methods=['GET'])
@optional_auth
def get_current_snapshot():
    """Get current snapshot"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate', 'has_debate': False}), 400
    
    snapshot = db.get_latest_snapshot(debate_id)
    
    frame_info = db.get_active_debate_frame(debate_id) if debate_id else None
    moderation_template = db.get_active_moderation_template() or {}
    policy_context = {
        'moderation_template_name': moderation_template.get('template_name') or moderation_template.get('name'),
        'moderation_template_version': moderation_template.get('version'),
    }

    if not snapshot:
        return jsonify({
            'has_debate': True,
            'has_snapshot': False,
            'snapshot_id': None,
            'timestamp': None,
            'trigger_type': None,
            'template_name': None,
            'template_version': None,
            'allowed_count': 0,
            'blocked_count': 0,
            'block_reasons': {},
            'borderline_rate': 0.0,
            'suppression_policy': {'k': 5, 'affected_buckets': [], 'affected_bucket_count': 0},
            'status': 'valid',
            'overall_for': None,
            'overall_against': None,
            'margin_d': None,
            'ci_d': None,
            'confidence': None,
            'verdict': 'NO VERDICT',
            'frame_mode': frame_info.get('frame_mode') if frame_info else get_frame_mode_flag(),
            'review_cadence_months': frame_info.get('review_cadence_months', 6) if frame_info else 6,
            'policy_context': policy_context,
        })
    
    return jsonify({
        'has_debate': True,
        'has_snapshot': True,
        'snapshot_id': snapshot['snapshot_id'],
        'timestamp': snapshot['timestamp'],
        'trigger_type': snapshot['trigger_type'],
        'template_name': snapshot['template_name'],
        'template_version': snapshot['template_version'],
        'allowed_count': snapshot['allowed_count'],
        'blocked_count': snapshot['blocked_count'],
        'block_reasons': json.loads(snapshot.get('block_reasons', '{}')),
        'borderline_rate': snapshot.get('borderline_rate', 0.0) or 0.0,
        'suppression_policy': json.loads(snapshot.get('suppression_policy_json', '{}') or '{}'),
        'status': snapshot.get('status', 'valid') or 'valid',
        'overall_for': snapshot['overall_for'],
        'overall_against': snapshot['overall_against'],
        'margin_d': snapshot['margin_d'],
        'ci_d': [snapshot['ci_d_lower'], snapshot['ci_d_upper']],
        'confidence': snapshot['confidence'],
        'verdict': snapshot['verdict'],
        'replay_manifest': json.loads(snapshot.get('replay_manifest_json', '{}') or '{}'),
        'input_hash_root': snapshot.get('input_hash_root'),
        'output_hash_root': snapshot.get('output_hash_root'),
        'recipe_versions': json.loads(snapshot.get('recipe_versions_json', '{}') or '{}'),
        'provider_metadata': json.loads(snapshot.get('provider_metadata_json', '{}') or '{}'),
        'cost_estimate': snapshot.get('cost_estimate'),
        'frame_mode': frame_info.get('frame_mode') if frame_info else get_frame_mode_flag(),
        'review_cadence_months': frame_info.get('review_cadence_months', 6) if frame_info else 6,
        'policy_context': policy_context,
    })


@app.route('/api/debate/snapshot-history', methods=['GET'])
@optional_auth
def get_snapshot_history():
    """Get snapshot history"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    history = debate_engine.get_snapshot_history(debate_id)
    
    return jsonify({
        'debate_id': debate_id,
        'snapshot_count': len(history),
        'snapshots': history
    })


@app.route('/api/debate/snapshot-diff', methods=['GET'])
@optional_auth
def get_snapshot_diff():
    """Compare two snapshots"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    old_id = request.args.get('old_snapshot_id')
    new_id = request.args.get('new_snapshot_id')
    
    try:
        if old_id and new_id:
            diff = debate_engine.diff_snapshots(old_id, new_id)
        else:
            diff = debate_engine.compare_consecutive_snapshots(debate_id)
            if diff is None:
                return jsonify({
                    'error': 'Need at least 2 snapshots for comparison'
                }), 400
        
        return jsonify(diff)
    
    except Exception as e:
        app.logger.error(f"Snapshot diff error: {str(e)}")
        return jsonify({
            'error': 'Failed to compare snapshots',
            'code': 'DIFF_ERROR'
        }), 500


# =============================================================================
# Topic Routes
# =============================================================================

@app.route('/api/debate/topics', methods=['GET'])
@optional_auth
def get_topics():
    """Get all topics"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    topics = db.get_topics_by_debate(debate_id)
    snapshot = db.get_latest_snapshot(debate_id)
    topic_scores = {}
    topic_diag = {}
    merge_diag = {}
    current_topic_ids = set()
    
    if snapshot:
        topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
        audits = debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
        topic_diag = audits.get('topic_diagnostics', {})
        merge_diag = audits.get('topic_merge_sensitivity', {})

        # Snapshot topic_scores stores both nested topic maps and legacy
        # per-topic-per-side entries. Keep only the nested topic ids so the
        # UI sees the current snapshot's topic set rather than historical rows.
        current_topic_ids = {
            topic_id
            for topic_id, score_map in topic_scores.items()
            if isinstance(topic_id, str)
            and isinstance(score_map, dict)
            and score_map
            and all(isinstance(side_scores, dict) for side_scores in score_map.values())
        }

        if not current_topic_ids:
            current_topic_ids = (
                set((topic_diag.get('pre_mass') or {}).keys())
                | set((topic_diag.get('sel_mass') or {}).keys())
            )

    if current_topic_ids:
        topics = [topic for topic in topics if topic.get('topic_id') in current_topic_ids]

    topics.sort(
        key=lambda topic: (
            -float(topic.get('relevance', 0.0) or 0.0),
            str(topic.get('name') or ''),
            str(topic.get('topic_id') or ''),
        )
    )
    
    topics_data = []
    for topic in topics:
        tid = topic['topic_id']
        topics_data.append({
            'topic_id': tid,
            'name': topic['name'],
            'scope': topic['scope'],
            'relevance': topic['relevance'],
            'drift_score': topic['drift_score'],
            'coherence': topic['coherence'],
            'distinctness': topic['distinctness'],
            'summary_for': topic.get('summary_for', ''),
            'summary_against': topic.get('summary_against', ''),
            'operation': topic.get('operation', 'created'),
            'parent_topic_ids': json.loads(topic.get('parent_topic_ids', '[]') or '[]'),
            'pre_mass': (topic_diag.get('pre_mass') or {}).get(tid, 0.0),
            'sel_mass': (topic_diag.get('sel_mass') or {}).get(tid, 0.0),
            'pre_to_sel_ratio': (topic_diag.get('pre_to_sel_ratio') or {}).get(tid, 0.0),
            'relevance_formula_mode': topic_diag.get('relevance_formula_mode', 'legacy_linear'),
            'scores': {
                'FOR': topic_scores.get(f"{tid}_FOR", {}),
                'AGAINST': topic_scores.get(f"{tid}_AGAINST", {})
            }
        })
    
    return jsonify({
        'topics': topics_data,
        'diagnostics': topic_diag,
        'dominance': topic_diag.get('dominance', {}),
        'micro_topic_rate': topic_diag.get('micro_topic_rate', 0.0),
        'mass_distribution_quantiles': topic_diag.get('mass_distribution_quantiles', {}),
        'gini_coefficient': topic_diag.get('gini_coefficient', 0.0),
        'merge_sensitivity': merge_diag,
        'relevance_formula_mode': topic_diag.get('relevance_formula_mode', 'legacy_linear'),
    })


@app.route('/api/debate/topics/<topic_id>', methods=['GET'])
@optional_auth
def get_topic(topic_id):
    """Get specific topic details"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    if not topic_id or not re.match(r'^[a-zA-Z0-9_-]+$', topic_id):
        raise ValidationError("Invalid topic ID")
    
    topic = db.get_topic(topic_id, debate_id)
    
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404
    
    # Get facts and arguments
    facts = db.get_canonical_facts_by_topic(topic_id)
    args = db.get_canonical_arguments_by_topic(topic_id)
    snapshot = db.get_latest_snapshot(debate_id)
    topic_scores = {}

    if snapshot:
        topic_scores = json.loads(snapshot.get('topic_scores', '{}'))

    return jsonify({
        'topic_id': topic['topic_id'],
        'name': topic['name'],
        'scope': topic['scope'],
        'relevance': topic['relevance'],
        'drift_score': topic['drift_score'],
        'coherence': topic['coherence'],
        'distinctness': topic['distinctness'],
        'summary_for': topic.get('summary_for', ''),
        'summary_against': topic.get('summary_against', ''),
        'operation': topic.get('operation', 'created'),
        'parent_topic_ids': json.loads(topic.get('parent_topic_ids', '[]') or '[]'),
        'scores': {
            'FOR': topic_scores.get(f"{topic_id}_FOR", {}),
            'AGAINST': topic_scores.get(f"{topic_id}_AGAINST", {})
        },
        'facts': [
            {
                'canon_fact_id': f['canon_fact_id'],
                'canon_fact_text': f['canon_fact_text'],
                'side': f['side'],
                'p_true': f['p_true'],
                'fact_type': f.get('fact_type', 'empirical'),
                'operationalization': f.get('operationalization', ''),
                'normative_provenance': f.get('normative_provenance', ''),
                'evidence_tier_counts': json.loads(f.get('evidence_tier_counts_json', '{}') or '{}'),
                'member_count': len(json.loads(f.get('member_fact_ids', '[]')))
            }
            for f in facts
        ],
        'arguments': [
            {
                'canon_arg_id': a['canon_arg_id'],
                'side': a['side'],
                'inference_text': a['inference_text'],
                'supporting_facts': json.loads(a.get('supporting_facts', '[]')),
                'member_count': len(json.loads(a.get('member_au_ids', '[]'))),
                'reasoning_score': a.get('reasoning_score', 0.5),
                'completeness_proxy': a.get('completeness_proxy', 0.0)
            }
            for a in args
        ]
    })


# =============================================================================
# Verdict & Audit Routes
# =============================================================================

@app.route('/api/debate/verdict', methods=['GET'])
@optional_auth
def get_verdict():
    """Get verdict"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    snapshot = db.get_latest_snapshot(debate_id)
    
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404
    
    # Sufficiency check: empty adjudication data should not render as a real verdict
    allowed_count = snapshot.get('allowed_count', 0) or 0
    has_scores = (
        snapshot.get('overall_for') is not None
        or snapshot.get('overall_against') is not None
        or snapshot.get('margin_d') is not None
    )
    if allowed_count == 0 or not has_scores:
        return jsonify({
            'snapshot_id': snapshot['snapshot_id'],
            'insufficient_data': True,
            'verdict': 'INSUFFICIENT_DATA',
            'message': 'Insufficient adjudication data. No allowed posts or scores are available for this debate.',
            'overall_for': None,
            'overall_against': None,
            'margin_d': None,
            'ci_d': [None, None],
            'confidence': None,
            'topic_contributions': [],
            'd_distribution': [],
            'replicate_composition_metadata': {
                'judge_count': int(os.getenv('NUM_JUDGES', '5')),
                'replicate_count': 0,
                'extraction_reruns': 2,
                'bootstrap_samples': 0,
                'structural_replicate_count': 0,
                'merge_sensitivity_channel': False,
            },
            'formula_metadata': formula_registry(),
            'factuality': {'tier_counts': {}},
        })
    
    topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
    topics = db.get_topics_by_debate(debate_id)
    audits = debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
    verdict_replicates = audits.get('verdict_replicates', {})
    dossier = audits.get('decision_dossier', {})
    
    contributions = []
    for topic in topics:
        tid = topic['topic_id']
        for_key = f"{tid}_FOR"
        against_key = f"{tid}_AGAINST"
        
        for_scores = topic_scores.get(for_key, {})
        against_scores = topic_scores.get(against_key, {})
        
        contribution = topic['relevance'] * (for_scores.get('quality', 0) - against_scores.get('quality', 0))
        contributions.append({
            'topic_id': tid,
            'name': topic['name'],
            'relevance': topic['relevance'],
            'q_for': for_scores.get('quality', 0),
            'q_against': against_scores.get('quality', 0),
            'contribution_to_d': round(contribution, 4)
        })
    
    return jsonify({
        'snapshot_id': snapshot['snapshot_id'],
        'overall_for': snapshot['overall_for'],
        'overall_against': snapshot['overall_against'],
        'margin_d': snapshot['margin_d'],
        'ci_d': [snapshot['ci_d_lower'], snapshot['ci_d_upper']],
        'confidence': snapshot['confidence'],
        'verdict': snapshot['verdict'],
        'topic_contributions': contributions,
        'd_distribution': verdict_replicates.get('d_distribution', []),
        'replicate_composition_metadata': {
            'judge_count': int(os.getenv('NUM_JUDGES', '5')),
            'replicate_count': verdict_replicates.get('replicate_composition', {}).get('replicate_count', len(verdict_replicates.get('d_distribution', []))),
            'extraction_reruns': 2,
            'bootstrap_samples': verdict_replicates.get('replicate_composition', {}).get('bootstrap_samples', len(verdict_replicates.get('d_distribution', []))),
            'structural_replicate_count': verdict_replicates.get('replicate_composition', {}).get('structural_replicate_count', 0),
            'merge_sensitivity_channel': bool(audits.get('topic_merge_sensitivity')),
        },
        'formula_metadata': formula_registry(),
        'factuality': {
            'tier_counts': {
                key: value.get('tier_distribution', {})
                for key, value in (dossier.get('evidence_gaps') or {}).items()
            }
        },
    })


@app.route('/api/debate/audits', methods=['GET'])
@optional_auth
def get_audits():
    """Get audits"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    snapshot = db.get_latest_snapshot(debate_id)
    
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404
    
    audits = debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
    topics = db.get_topics_by_debate(debate_id)
    
    topic_geometry = [
        {
            'topic_id': t['topic_id'],
            'name': t['name'],
            'content_mass': t['relevance'],
            'drift_score': t['drift_score'],
            'coherence': t['coherence'],
            'distinctness': t['distinctness'],
            'operation': t.get('operation', 'created'),
            'parent_topic_ids': json.loads(t.get('parent_topic_ids', '[]') or '[]')
        }
        for t in topics
    ]

    extraction_stability = audits.get('extraction_stability', {})
    label_symmetry = audits.get('side_label_symmetry', {})
    relevance_sensitivity = audits.get('relevance_sensitivity', {})
    topic_diag = audits.get('topic_diagnostics', {})

    return jsonify({
        'snapshot_id': snapshot['snapshot_id'],
        'audit_schema_version': AUDIT_SCHEMA_VERSION,
        'timestamp': snapshot['timestamp'],
        'verdict': snapshot['verdict'],
        'confidence': snapshot['confidence'],
        'topic_geometry': topic_geometry,
        'topic_dominance': topic_diag.get('dominance', {}),
        'topic_concentration': {
            'micro_topic_rate': topic_diag.get('micro_topic_rate', 0.0),
            'mass_distribution_quantiles': topic_diag.get('mass_distribution_quantiles', {}),
            'gini_coefficient': topic_diag.get('gini_coefficient', 0.0),
        },
        'extraction_stability': {
            'fact_overlap': extraction_stability.get('fact_overlap', {}),
            'argument_overlap': extraction_stability.get('argument_overlap', {}),
            'mismatches': extraction_stability.get('mismatches', []),
            'num_runs': extraction_stability.get('num_runs', 0),
            'stability_score': extraction_stability.get('stability_score', 0)
        },
        'evaluator_disagreement': audits.get('evaluator_variance', {}),
        'label_symmetry': {
            'median_delta_d': label_symmetry.get('median_delta_d', 0),
            'abs_delta_d': label_symmetry.get('abs_delta_d', 0),
            'original_d': label_symmetry.get('original_d', 0),
            'swapped_d': label_symmetry.get('swapped_d', 0),
            'topic_deltas': label_symmetry.get('topic_deltas', {}),
            'interpretation': label_symmetry.get('interpretation', '')
        },
        'relevance_sensitivity': relevance_sensitivity,
        'frame_sensitivity': audits.get('frame_sensitivity', {}),
        'integrity_indicators': audits.get('integrity_indicators', {}),
        'participation_concentration': audits.get('participation_concentration', {}),
        'budget_adequacy': audits.get('budget_adequacy', {}),
        'centrality_cap_effect': audits.get('centrality_cap_effect', {}),
        'rarity_utilization': audits.get('rarity_utilization', {}),
        'merge_sensitivity': audits.get('topic_merge_sensitivity', {}),
        'coverage_adequacy_trace': audits.get('coverage_adequacy_trace', {}),
        'selection_transparency': audits.get('selection_transparency', {}),
        'formula_registry': audits.get('formula_registry', formula_registry()),
    })


@app.route('/api/debate/evidence-targets', methods=['GET'])
@optional_auth
def get_evidence_targets():
    """Get evidence targets"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    snapshot_id = request.args.get('snapshot_id')
    
    try:
        targets = debate_engine.get_evidence_targets(debate_id, snapshot_id)
        return jsonify(targets)
    except Exception as e:
        app.logger.error(f"Evidence targets error: {str(e)}")
        return jsonify({'error': 'Failed to get evidence targets'}), 500


# =============================================================================
# Modulation Template Visibility Endpoints
# =============================================================================

@app.route('/api/debate/modulation-info', methods=['GET'])
@optional_auth
def get_modulation_info():
    """Get the currently active modulation template metadata."""
    return jsonify(debate_engine.get_modulation_info())


@app.route('/api/debate/modulation-templates', methods=['GET'])
@optional_auth
def get_modulation_templates():
    """List builtin modulation templates and identify the active base template."""
    active = db.get_active_moderation_template() or {}
    return jsonify({
        'templates': ModulationEngine.list_builtin_templates(),
        'active_base_template_id': active.get('base_template_id'),
    })


# =============================================================================
# Frame Endpoints (LSD §5)
# =============================================================================

@app.route('/api/governance/frames', methods=['GET'])
@optional_auth
def get_frames():
    """Get active frame and available frames"""
    debate_id = get_session_debate_id()
    active_frame = db.get_active_debate_frame(debate_id) if debate_id else None
    frames = db.get_debate_frames(debate_id) if debate_id else []
    registry_frame = debate_engine.get_frame_info()
    frame_info = active_frame or registry_frame
    if frame_info and "statement" not in frame_info:
        dossier = {
            "statement": frame_info.get("frame_summary", ""),
            "scope": "; ".join(frame_info.get("scope_constraints", [])),
            "grounding_rationale": "Published active debate frame selected through the governance workflow.",
            "inclusion_justification": "; ".join(frame_info.get("evaluation_criteria", [])),
            "exclusion_note": frame_info.get("notes", ""),
            "known_tensions": frame_info.get("scope_constraints", []),
            "prioritized_values": frame_info.get("evaluation_criteria", [])[:4],
        }
        frame_info = {
            **frame_info,
            "statement": frame_info.get("frame_summary", ""),
            "scope": dossier["scope"],
            "dossier": dossier,
            "next_review_date": frame_info.get("review_date"),
            "review_cadence_months": frame_info.get("review_cadence_months", 6),
            "emergency_override_path": "Use /api/governance/emergency-override with a published rationale.",
        }
    return jsonify({
        'active_frame': frame_info,
        'frames': frames,
        'mode': get_frame_mode_flag(),
        'frame_set_version': frame_info.get('version') if frame_info else None,
        'review_schedule': [
            {
                'frame_id': frame.get('frame_id'),
                'debate_id': frame.get('debate_id'),
                'review_date': frame.get('review_date'),
                'review_cadence_months': frame.get('review_cadence_months', 6),
            }
            for frame in frames
        ],
    })


@app.route('/api/debate/<debate_id>/frame-petitions', methods=['GET'])
@optional_auth
def list_frame_petitions(debate_id):
    """List public frame petitions for a debate."""
    return jsonify({
        'petitions': db.get_frame_petitions(debate_id=debate_id),
    })


@app.route('/api/debate/<debate_id>/frame-petitions', methods=['POST'])
@login_required
def create_frame_petition(debate_id):
    """Submit a candidate frame petition separate from debate proposals."""
    if not db.get_debate(debate_id):
        return jsonify({'error': 'Debate not found'}), 404
    data = request.get_json() or {}
    candidate = data.get('candidate_frame') or data
    if not isinstance(candidate, dict):
        return jsonify({'error': 'candidate_frame must be an object'}), 400
    petition = db.create_frame_petition(
        debate_id=debate_id,
        proposer_user_id=g.user['user_id'],
        candidate_frame=candidate,
    )
    debate_engine.governance.log_change(
        change_type='frame_petition',
        description=f"Frame petition submitted for {debate_id}",
        changed_by=g.user['user_id'],
        justification='Public frame petition intake',
        new_value=petition.get('petition_id'),
    )
    return jsonify({'petition': petition}), 201


@app.route('/api/admin/frame-petitions/<petition_id>/accept', methods=['POST'])
@admin_required
def accept_frame_petition(petition_id):
    """Accept a frame petition and activate a new frame version."""
    petition = db.get_frame_petition(petition_id)
    if not petition:
        return jsonify({'error': 'Petition not found'}), 404
    reviewer_user_id = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    candidate = petition.get('candidate_frame') or {}
    try:
        debate = debate_engine.create_frame_version(petition['debate_id'], candidate)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400
    decision = {
        'decision': 'accepted',
        'reason': (request.get_json() or {}).get('reason', 'Accepted by admin governance review'),
        'activated_frame_id': debate.get('active_frame_id'),
    }
    updated = db.update_frame_petition_status(petition_id, 'accepted', decision, reviewer_user_id)
    debate_engine.governance.log_change(
        change_type='frame',
        description=f"Accepted frame petition {petition_id}",
        changed_by=reviewer_user_id,
        justification=decision['reason'],
        new_value=debate.get('active_frame_id'),
    )
    return jsonify({'petition': updated, 'debate': debate})


@app.route('/api/admin/frame-petitions/<petition_id>/reject', methods=['POST'])
@admin_required
def reject_frame_petition(petition_id):
    """Reject a frame petition with a published governance decision."""
    petition = db.get_frame_petition(petition_id)
    if not petition:
        return jsonify({'error': 'Petition not found'}), 404
    reviewer_user_id = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    payload = request.get_json() or {}
    decision = {
        'decision': 'rejected',
        'reason': payload.get('reason', 'Rejected by admin governance review'),
    }
    updated = db.update_frame_petition_status(petition_id, 'rejected', decision, reviewer_user_id)
    debate_engine.governance.log_change(
        change_type='frame',
        description=f"Rejected frame petition {petition_id}",
        changed_by=reviewer_user_id,
        justification=decision['reason'],
        previous_value=petition_id,
    )
    return jsonify({'petition': updated})


@app.route('/api/governance/frame-cadence', methods=['GET'])
@optional_auth
def get_frame_cadence():
    debate_id = get_session_debate_id()
    frames = db.get_debate_frames(debate_id) if debate_id else []
    return jsonify({
        'debate_id': debate_id,
        'review_schedule': [
            {
                'frame_id': frame.get('frame_id'),
                'version': frame.get('version'),
                'review_date': frame.get('review_date'),
                'review_cadence_months': frame.get('review_cadence_months', 6),
                'governance_decision_id': frame.get('governance_decision_id'),
            }
            for frame in frames
        ],
    })


@app.route('/api/governance/frame-cadence', methods=['POST'])
@admin_required
def set_frame_cadence():
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    payload = request.get_json() or {}
    cadence = int(payload.get('review_cadence_months') or 6)
    review_date = payload.get('review_date')
    db.update_frame_review_schedule(debate_id, review_date, cadence)
    debate_engine.governance.log_change(
        change_type='frame_cadence',
        description=f"Updated frame review cadence for {debate_id}",
        changed_by=(getattr(g, 'user', None) or {}).get('user_id') or 'admin',
        justification=payload.get('justification', 'Frame stability review cadence update'),
        new_value=json.dumps({'review_date': review_date, 'review_cadence_months': cadence}),
    )
    return get_frame_cadence()


@app.route('/api/governance/emergency-override', methods=['POST'])
@admin_required
def emergency_frame_override():
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    payload = request.get_json() or {}
    reason = validate_string(payload.get('reason'), 'Emergency reason', min_length=10, max_length=2000)
    target_frame_id = payload.get('frame_id')
    active = db.get_active_debate_frame(debate_id)
    frame_id = target_frame_id or (active or {}).get('frame_id')
    if not frame_id:
        return jsonify({'error': 'No active frame'}), 404
    if target_frame_id:
        db.set_active_frame(debate_id, target_frame_id)
    actor = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    governance_decision_id = f"gov_{uuid.uuid4().hex[:10]}"
    db.apply_emergency_override(frame_id, reason, actor, governance_decision_id)
    debate_engine.governance.log_change(
        change_type='emergency_override',
        description=f"Emergency frame override for {debate_id}",
        changed_by=actor,
        justification=reason,
        new_value=frame_id,
        approval_references=[governance_decision_id],
    )
    return jsonify({
        'governance_decision_id': governance_decision_id,
        'frame_id': frame_id,
        'reason': reason,
    })


# =============================================================================
# Decision Dossier Endpoints (LSD §17)
# =============================================================================

@app.route('/api/debate/decision-dossier', methods=['GET'])
@optional_auth
def get_decision_dossier():
    """Get decision dossier for current snapshot"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    snapshot = db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404
    
    # Sufficiency check
    allowed_count = snapshot.get('allowed_count', 0) or 0
    has_scores = (
        snapshot.get('overall_for') is not None
        or snapshot.get('overall_against') is not None
        or snapshot.get('margin_d') is not None
    )
    if allowed_count == 0 or not has_scores:
        return jsonify({
            'snapshot_id': snapshot['snapshot_id'],
            'insufficient_data': True,
            'verdict': 'INSUFFICIENT_DATA',
            'message': 'Insufficient adjudication data. No allowed posts or scores are available for this debate.',
            'frame': debate_engine.get_frame_info(),
            'overall_for': None,
            'overall_against': None,
            'margin_d': None,
            'evidence_gaps': {},
            'evidence_gap_summary': {},
            'decisive_premises': [],
            'decisive_arguments': [],
            'counterfactuals': {},
            'priority_gaps': {},
            'insufficiency_sensitivity': {},
            'unselected_tail_summary': {},
            'formula_metadata': formula_registry(),
            'selection_diagnostics': {},
        })
    
    # Retrieve decision dossier from snapshot audits if available
    audits = debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
    saved_dossier = audits.get('decision_dossier', {})
    
    # Build evidence gap summary from topic scores
    topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
    topics = db.get_topics_by_debate(debate_id)
    evidence_gaps = {}
    for topic in topics:
        tid = topic['topic_id']
        for side in ['FOR', 'AGAINST']:
            scores = topic_scores.get(f"{tid}_{side}", {})
            evidence_gaps[f"{tid}_{side}"] = {
                'insufficiency_rate': scores.get('insufficiency_rate', 0.0),
                'f_supported_only': scores.get('f_supported_only', 0.5),
                'f_all': scores.get('factuality', 0.5),
            }
    
    # Get counterfactuals from latest snapshot generation if available
    selection_diag = audits.get('selection_transparency', {})
    
    return jsonify({
        'snapshot_id': snapshot['snapshot_id'],
        'frame': debate_engine.get_frame_info(),
        'verdict': snapshot['verdict'],
        'confidence': snapshot['confidence'],
        'overall_for': snapshot['overall_for'],
        'overall_against': snapshot['overall_against'],
        'margin_d': snapshot['margin_d'],
        'evidence_gaps': saved_dossier.get('evidence_gaps', evidence_gaps),
        'evidence_gap_summary': saved_dossier.get('evidence_gaps', evidence_gaps),
        'decisive_premises': saved_dossier.get('decisive_premises', []),
        'decisive_arguments': saved_dossier.get('decisive_arguments', []),
        'counterfactuals': saved_dossier.get('counterfactuals', {}),
        'priority_gaps': saved_dossier.get('priority_gaps', {}),
        'insufficiency_sensitivity': saved_dossier.get('insufficiency_sensitivity', {}),
        'unselected_tail_summary': saved_dossier.get('unselected_tail_summary', {}),
        'formula_metadata': saved_dossier.get('formula_metadata', formula_registry()),
        'selection_diagnostics': selection_diag,
    })


# =============================================================================
# Governance Endpoints (LSD §20)
# =============================================================================

@app.route('/api/governance/changelog', methods=['GET'])
@optional_auth
def get_changelog():
    """Get system changelog"""
    change_type = request.args.get('change_type')
    limit = request.args.get('limit', 100, type=int)
    entries = debate_engine.governance.get_changelog(change_type=change_type, limit=limit)
    return jsonify({'entries': entries})


@app.route('/api/governance/appeals', methods=['GET'])
@login_required
def get_appeals():
    """Get appeals"""
    debate_id = get_session_debate_id()
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    
    from governance import AppealStatus
    status_enum = None
    if status:
        try:
            status_enum = AppealStatus(status)
        except ValueError:
            return jsonify({'error': 'Invalid status'}), 400
    
    appeals = debate_engine.governance.get_appeals(
        debate_id=debate_id,
        status=status_enum,
        limit=limit
    )
    return jsonify({'appeals': appeals})


@app.route('/api/debate/<debate_id>/appeals', methods=['POST'])
@login_required
def submit_appeal(debate_id):
    """Submit a new appeal for a specific debate."""
    snapshot = db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404
    
    data = request.get_json() or {}
    appeal_type = validate_string(
        data.get('appeal_type', 'moderation_error'),
        'Appeal type',
        max_length=50
    )
    valid_types = ['moderation_error', 'topic_misframing', 'missing_argument', 'provenance_error']
    if appeal_type not in valid_types:
        return jsonify({'error': f'Invalid appeal type. Must be one of: {valid_types}'}), 400
    
    description = validate_string(data.get('description') or data.get('grounds'), 'Description', min_length=10, max_length=2000)
    evidence = data.get('evidence_references', [])
    relief = validate_string(data.get('requested_relief') or 'Review and correct snapshot.', 'Requested relief', min_length=5, max_length=500)
    
    appeal_id = debate_engine.governance.submit_appeal(
        debate_id=debate_id,
        snapshot_id=snapshot['snapshot_id'],
        claimant_id=g.user['user_id'],
        grounds=f"[{appeal_type}] {description}",
        evidence_references=evidence if isinstance(evidence, list) else [],
        requested_relief=relief
    )
    
    return jsonify({'appeal_id': appeal_id, 'status': 'submitted'}), 201


@app.route('/api/debate/<debate_id>/appeals/mine', methods=['GET'])
@login_required
def get_my_appeals(debate_id):
    """Get appeals submitted by the current user for a debate."""
    appeals = debate_engine.governance.get_appeals(debate_id=debate_id, limit=500)
    my_appeals = [a for a in appeals if a.get('claimant_id') == g.user['user_id']]
    return jsonify({'appeals': my_appeals})


@app.route('/api/admin/appeals', methods=['GET'])
@admin_required
def get_admin_appeals():
    """Admin queue: get all appeals."""
    status = request.args.get('status')
    from governance import AppealStatus
    status_enum = None
    if status:
        try:
            status_enum = AppealStatus(status)
        except ValueError:
            return jsonify({'error': 'Invalid status'}), 400
    appeals = debate_engine.governance.get_appeals(status=status_enum, limit=500)
    return jsonify({'appeals': appeals})


@app.route('/api/admin/appeals/<appeal_id>/resolve', methods=['POST'])
@admin_required
def resolve_appeal(appeal_id):
    """Admin action: resolve an appeal with published rationale."""
    data = request.get_json() or {}
    decision = validate_string(data.get('decision'), 'Decision', max_length=20)
    valid_decisions = ['accepted', 'rejected']
    if decision not in valid_decisions:
        return jsonify({'error': f'Decision must be one of: {valid_decisions}'}), 400
    
    decision_reason = validate_string(data.get('decision_reason'), 'Decision reason', min_length=10, max_length=2000)
    resolution = data.get('resolution', '')
    
    from governance import AppealStatus
    status = AppealStatus.ACCEPTED if decision == 'accepted' else AppealStatus.REJECTED
    
    success = debate_engine.governance.review_appeal(
        appeal_id=appeal_id,
        reviewer_id=g.user['user_id'],
        decision=status,
        decision_reason=decision_reason,
        resolution=resolution
    )
    
    if not success:
        return jsonify({'error': 'Appeal not found or already resolved'}), 404
    
    # If upheld, mark snapshot as superseded
    if decision == 'accepted':
        appeals = debate_engine.governance.get_appeals(limit=500)
        appeal = next((a for a in appeals if a['appeal_id'] == appeal_id), None)
        if appeal:
            db.update_snapshot_status(appeal['snapshot_id'], 'superseded')
    
    log_admin_action('appeal_resolve', f"Resolved appeal {appeal_id} as {decision}")
    return jsonify({'appeal_id': appeal_id, 'status': decision, 'reason': decision_reason}), 200


@app.route('/api/governance/judge-pool', methods=['GET'])
@optional_auth
def get_judge_pool():
    """Get judge pool summary"""
    summary = debate_engine.governance.get_judge_pool_summary()
    return jsonify(summary)


@app.route('/api/governance/judge-pool/composition', methods=['POST'])
@admin_required
def record_judge_pool_composition():
    """Record judge pool composition entry."""
    payload = request.get_json() or {}
    composition_id = debate_engine.governance.record_judge_pool_composition(
        category=payload.get('category', 'general'),
        count=payload.get('count', 0),
        qualification_rubric=payload.get('qualification_rubric', {}),
        snapshot_id=payload.get('snapshot_id'),
    )
    return jsonify({'composition_id': composition_id}), 201


@app.route('/api/governance/judge-pool/rotation-policy', methods=['GET'])
@optional_auth
def get_rotation_policy():
    """Get active rotation policy."""
    policy = debate_engine.governance.get_rotation_policy()
    return jsonify(policy or {})


@app.route('/api/governance/judge-pool/rotation-policy', methods=['POST'])
@admin_required
def set_rotation_policy():
    """Set rotation policy."""
    payload = request.get_json() or {}
    policy_id = debate_engine.governance.set_rotation_policy(
        max_consecutive_snapshots=payload.get('max_consecutive_snapshots', 5),
        cooldown_snapshots=payload.get('cooldown_snapshots', 2),
    )
    return jsonify({'policy_id': policy_id}), 201


@app.route('/api/governance/judge-pool/calibration-protocol', methods=['GET'])
@optional_auth
def get_calibration_protocol():
    """Get active calibration protocol."""
    protocol = debate_engine.governance.get_calibration_protocol()
    return jsonify(protocol or {})


@app.route('/api/governance/judge-pool/calibration-protocol', methods=['POST'])
@admin_required
def set_calibration_protocol():
    """Set calibration protocol."""
    payload = request.get_json() or {}
    protocol_id = debate_engine.governance.set_calibration_protocol(
        guideline_version=payload.get('guideline_version', 'v1.0'),
        shared_guidelines=payload.get('shared_guidelines', {}),
        inter_judge_consistency_check=payload.get('inter_judge_consistency_check', {}),
    )
    return jsonify({'protocol_id': protocol_id}), 201


@app.route('/api/governance/judge-pool/conflict-of-interest', methods=['POST'])
@admin_required
def log_conflict_of_interest():
    """Log a conflict-of-interest entry."""
    payload = request.get_json() or {}
    entry_id = debate_engine.governance.log_conflict_of_interest(
        judge_id=payload.get('judge_id'),
        conflict_type=payload.get('conflict_type', 'recusal'),
        description=payload.get('description', ''),
        debate_id=payload.get('debate_id'),
        topic_id=payload.get('topic_id'),
    )
    return jsonify({'entry_id': entry_id}), 201


@app.route('/api/governance/fairness-audits', methods=['GET'])
@optional_auth
def get_fairness_audits():
    """Get fairness audit summary"""
    limit = request.args.get('limit', 100, type=int)
    summary = debate_engine.governance.get_fairness_audit_summary(limit=limit)
    return jsonify(summary)


@app.route('/api/governance/incidents', methods=['GET'])
@optional_auth
def get_incidents():
    """Get incidents"""
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    
    from governance import IncidentSeverity
    severity_enum = None
    severity = request.args.get('severity')
    if severity:
        try:
            severity_enum = IncidentSeverity(severity)
        except ValueError:
            return jsonify({'error': 'Invalid severity'}), 400
    
    incidents = debate_engine.governance.get_incidents(
        status=status,
        severity=severity_enum,
        limit=limit
    )
    return jsonify({'incidents': incidents})


@app.route('/api/debate/<debate_id>/incidents', methods=['GET'])
@optional_auth
def get_debate_incidents(debate_id):
    """Get public incidents affecting one debate."""
    all_incidents = debate_engine.governance.get_incidents(limit=500)
    incidents = [
        incident for incident in all_incidents
        if debate_id in incident.get('affected_debates', [])
    ]
    return jsonify({'debate_id': debate_id, 'incidents': incidents})


@app.route('/api/admin/snapshots/<snapshot_id>/verify', methods=['POST'])
@admin_required
def verify_snapshot_endpoint(snapshot_id):
    """Verify snapshot determinism by recomputing input/output hashes."""
    result = debate_engine.verify_snapshot(snapshot_id)
    return jsonify(result)


@app.route('/api/admin/snapshots/<snapshot_id>/verify-job', methods=['POST'])
@admin_required
def enqueue_verify_job(snapshot_id):
    """Enqueue a background verification job for a snapshot."""
    job_id = job_queue.create_job(
        'verify',
        {
            'snapshot_id': snapshot_id,
            'user_id': g.user['user_id'],
        },
        runtime_profile_id=CURRENT_RUNTIME_PROFILE["runtime_profile_id"],
    )
    log_admin_action('verify_job_enqueue', f"Enqueued verification job {job_id} for snapshot {snapshot_id}")
    return jsonify({'job_id': job_id, 'status': 'queued'}), 202


@app.route('/api/audit/export/<snapshot_id>', methods=['GET'])
@admin_required
def export_audit_bundle(snapshot_id):
    """Export a verifiable audit bundle for authorized auditors."""
    bundle = debate_engine.export_audit_bundle(snapshot_id)
    if 'error' in bundle:
        return jsonify(bundle), 404
    return jsonify(bundle)


@app.route('/api/admin/snapshots/<snapshot_id>/mark-incident', methods=['POST'])
@admin_required
def mark_snapshot_incident(snapshot_id):
    """Mark a snapshot as incident without deleting or mutating prior outputs."""
    snapshot = debate_engine.get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({'error': 'Snapshot not found'}), 404
    payload = request.get_json() or {}
    severity_raw = (payload.get('severity') or 'medium').lower()
    from governance import IncidentSeverity
    try:
        severity = IncidentSeverity(severity_raw)
    except ValueError:
        return jsonify({'error': 'Invalid severity'}), 400
    description = validate_string(payload.get('description'), 'Description', min_length=10, max_length=2000)
    remediation_plan = validate_string(payload.get('remediation_plan') or 'Publish additive correction snapshot after review.', 'Remediation plan', min_length=5, max_length=2000)
    actor = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    incident_id = debate_engine.governance.report_incident(
        severity=severity,
        reported_by=actor,
        description=description,
        affected_debates=[snapshot['debate_id']],
        trigger_snapshot_ids=[snapshot_id],
        snapshot_id=snapshot_id,
        affected_outputs=payload.get('affected_outputs') or {},
        remediation_plan=remediation_plan,
    )
    db.update_snapshot_status(snapshot_id, 'incident')
    return jsonify({
        'incident_id': incident_id,
        'snapshot_id': snapshot_id,
        'status': 'incident',
    }), 201


@app.route('/metrics', methods=['GET'])
def get_metrics():
    """Prometheus-style metrics endpoint for observability."""
    lines = []
    lines.append('# HELP snapshot_count_total Total snapshots generated')
    lines.append('# TYPE snapshot_count_total counter')
    try:
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM snapshots")
        count = cursor.fetchone()['c']
        conn.close()
        lines.append(f'snapshot_count_total {count}')
    except Exception:
        lines.append('snapshot_count_total 0')
    lines.append('# HELP llm_calls_total Total LLM API calls')
    lines.append('# TYPE llm_calls_total counter')
    usage = debate_engine.llm_client.get_usage_summary()
    lines.append(f'llm_calls_total{{provider="{usage.get("provider", "mock")}"}} {usage.get("call_count", 0)}')
    lines.append('# HELP llm_tokens_total Total LLM tokens consumed')
    lines.append('# TYPE llm_tokens_total counter')
    lines.append(f'llm_tokens_total{{type="prompt"}} {usage.get("prompt_tokens", 0)}')
    lines.append(f'llm_tokens_total{{type="completion"}} {usage.get("completion_tokens", 0)}')
    return '\n'.join(lines) + '\n', 200, {'Content-Type': 'text/plain; version=0.0.4'}


@app.route('/api/governance/summary', methods=['GET'])
@optional_auth
def get_governance_summary():
    """Get complete governance summary"""
    summary = debate_engine.governance.get_governance_summary()
    return jsonify(summary)


# =============================================================================
# Static File Serving
# =============================================================================

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    """Serve static files"""
    if not path:
        path = 'index.html'
    # Security: prevent directory traversal
    path = path.replace('..', '').lstrip('/')
    
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    
    try:
        return send_from_directory(frontend_dir, path)
    except:
        # Return index.html for SPA routing
        return send_from_directory(frontend_dir, 'index.html')


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("Blind Debate Adjudicator Server v3")
    print("=" * 60)
    print("Features:")
    print("  - Multi-debate support per user")
    print("  - JWT authentication")
    print("  - Input validation")
    print("  - Session-based debate management")
    print("-" * 60)
    print("API available at: http://localhost:5000")
    print("Web UI available at: http://localhost:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)

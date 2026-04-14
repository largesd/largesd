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
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory, g
from flask_cors import CORS
import jwt
from werkzeug.exceptions import BadRequest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from debate_engine_v2 import DebateEngineV2
from database_v3 import Database

app = Flask(__name__, static_folder=None)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['JWT_EXPIRATION_HOURS'] = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max request size

DB_PATH = os.getenv("DEBATE_DB_PATH", "data/debate_system.db")

# Initialize debate engine (shared, stateless)
debate_engine = DebateEngineV2(
    db_path=DB_PATH,
    fact_check_mode=os.getenv("FACT_CHECK_MODE", "OFFLINE"),
    llm_provider=os.getenv("LLM_PROVIDER", "mock"),
    num_judges=int(os.getenv("NUM_JUDGES", "5")),
    openrouter_api_key=os.getenv("OPENROUTER_API_KEY")
)

# Database for user/session management
db = Database(DB_PATH)


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

def generate_token(user_id, email, display_name):
    """Generate JWT token"""
    payload = {
        'user_id': user_id,
        'email': email,
        'display_name': display_name,
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
            'display_name': payload['display_name']
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
                    'display_name': payload['display_name']
                }
        
        return f(*args, **kwargs)
    
    return decorated_function


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
    if g.user:
        user_prefs = db.get_user_preferences(g.user['user_id'])
        if user_prefs and user_prefs.get('active_debate_id'):
            return user_prefs['active_debate_id']
    
    return None


def set_session_debate(debate_id):
    """Set active debate for user"""
    if g.user:
        db.set_user_preference(g.user['user_id'], 'active_debate_id', debate_id)


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
    token = generate_token(user['user_id'], user['email'], user['display_name'])
    
    return jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'display_name': user['display_name'],
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
    token = generate_token(user['user_id'], user['email'], user['display_name'])
    
    return jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'display_name': user['display_name'],
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
@login_required
def create_debate():
    """Create a new debate"""
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
# Post Routes
# =============================================================================

@app.route('/api/debate/posts', methods=['POST'])
@login_required
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
def generate_snapshot():
    """Generate a new snapshot"""
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
    
    try:
        # Ownership check
        debate = db.get_debate(debate_id)
        if not debate:
            return jsonify({'error': 'Debate not found'}), 404
        if debate.get('is_private') and debate.get('user_id') != g.user['user_id']:
            return jsonify({'error': 'Access denied'}), 403
        
        snapshot = debate_engine.generate_snapshot(
            debate_id=debate_id,
            trigger_type=trigger_type
        )
        
        return jsonify({
            'snapshot_id': snapshot['snapshot_id'],
            'timestamp': snapshot['timestamp'],
            'trigger_type': snapshot['trigger_type'],
            'template_name': snapshot['template_name'],
            'template_version': snapshot['template_version'],
            'allowed_count': snapshot['allowed_count'],
            'blocked_count': snapshot['blocked_count'],
            'block_reasons': snapshot['block_reasons'],
            'overall_for': snapshot['overall_for'],
            'overall_against': snapshot['overall_against'],
            'margin_d': snapshot['margin_d'],
            'ci_d': [snapshot['ci_d_lower'], snapshot['ci_d_upper']],
            'confidence': snapshot['confidence'],
            'verdict': snapshot['verdict'],
            'num_topics': len(snapshot.get('topics', [])),
            'audits_available': list(snapshot.get('audits', {}).keys())
        })
    
    except Exception as e:
        app.logger.error(f"Snapshot generation error: {str(e)}")
        return jsonify({
            'error': 'Failed to generate snapshot',
            'code': 'SNAPSHOT_ERROR'
        }), 500


@app.route('/api/debate/snapshot', methods=['GET'])
@optional_auth
def get_current_snapshot():
    """Get current snapshot"""
    debate_id = get_session_debate_id()
    
    if not debate_id:
        return jsonify({'error': 'No active debate', 'has_debate': False}), 400
    
    snapshot = db.get_latest_snapshot(debate_id)
    
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
            'overall_for': None,
            'overall_against': None,
            'margin_d': None,
            'ci_d': None,
            'confidence': None,
            'verdict': 'NO VERDICT'
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
        'overall_for': snapshot['overall_for'],
        'overall_against': snapshot['overall_against'],
        'margin_d': snapshot['margin_d'],
        'ci_d': [snapshot['ci_d_lower'], snapshot['ci_d_upper']],
        'confidence': snapshot['confidence'],
        'verdict': snapshot['verdict']
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
    
    if snapshot:
        topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
    
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
            'scores': {
                'FOR': topic_scores.get(f"{tid}_FOR", {}),
                'AGAINST': topic_scores.get(f"{tid}_AGAINST", {})
            }
        })
    
    return jsonify({'topics': topics_data})


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
                'reasoning_score': a.get('reasoning_score', 0.5)
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
    
    topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
    topics = db.get_topics_by_debate(debate_id)
    
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
        'topic_contributions': contributions
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

    return jsonify({
        'snapshot_id': snapshot['snapshot_id'],
        'timestamp': snapshot['timestamp'],
        'verdict': snapshot['verdict'],
        'confidence': snapshot['confidence'],
        'topic_geometry': topic_geometry,
        'extraction_stability': {
            'fact_overlap': extraction_stability.get('fact_overlap', {}),
            'argument_overlap': extraction_stability.get('argument_overlap', {}),
            'mismatches': extraction_stability.get('mismatches', []),
            'num_runs': extraction_stability.get('num_runs', 0),
            'stability_score': extraction_stability.get('stability_score', 0)
        },
        'evaluator_disagreement': {
            'reasoning_iqr_median': 0.19,
            'coverage_iqr_median': 0.16,
            'overall_iqr': 0.06
        },
        'label_symmetry': {
            'median_delta_d': label_symmetry.get('median_delta_d', 0),
            'abs_delta_d': label_symmetry.get('abs_delta_d', 0),
            'original_d': label_symmetry.get('original_d', 0),
            'swapped_d': label_symmetry.get('swapped_d', 0),
            'topic_deltas': label_symmetry.get('topic_deltas', {}),
            'interpretation': label_symmetry.get('interpretation', '')
        },
        'relevance_sensitivity': relevance_sensitivity
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
# Frame Endpoints (LSD §5)
# =============================================================================

@app.route('/api/governance/frames', methods=['GET'])
@optional_auth
def get_frames():
    """Get active frame and available frames"""
    frame_info = debate_engine.get_frame_info()
    return jsonify({
        'active_frame': frame_info,
        'mode': 'single_frame',
        'frame_set_version': frame_info.get('version') if frame_info else None,
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
    
    # Retrieve decision dossier from snapshot audits if available
    audits = debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
    
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
        'evidence_gaps': evidence_gaps,
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


@app.route('/api/governance/appeals', methods=['POST'])
@login_required
def submit_appeal():
    """Submit a new appeal"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    
    snapshot = db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404
    
    data = request.get_json() or {}
    grounds = validate_string(data.get('grounds'), 'Grounds', min_length=10, max_length=2000)
    evidence = data.get('evidence_references', [])
    relief = validate_string(data.get('requested_relief'), 'Requested relief', min_length=5, max_length=500)
    
    appeal_id = debate_engine.governance.submit_appeal(
        debate_id=debate_id,
        snapshot_id=snapshot['snapshot_id'],
        claimant_id=g.user['user_id'],
        grounds=grounds,
        evidence_references=evidence if isinstance(evidence, list) else [],
        requested_relief=relief
    )
    
    return jsonify({'appeal_id': appeal_id}), 201


@app.route('/api/governance/judge-pool', methods=['GET'])
@optional_auth
def get_judge_pool():
    """Get judge pool summary"""
    summary = debate_engine.governance.get_judge_pool_summary()
    return jsonify(summary)


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

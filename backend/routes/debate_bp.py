"""Debate blueprint — debate CRUD, posts, frame petitions, incidents."""
import re

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.sanitize import sanitize_html
from backend.utils.decorators import admin_required, login_required, optional_auth
from backend.utils.helpers import get_session_debate_id, set_session_debate
from backend.utils.validators import ValidationError, validate_side, validate_string, validate_topic_id

debate_bp = Blueprint('debate', __name__)


# ---------------------------------------------------------------------------
# Debate CRUD
# ---------------------------------------------------------------------------
@debate_bp.route('/api/debates', methods=['GET'])
@optional_auth
def list_debates():
    """List debates accessible to user"""
    if g.user:
        debates = extensions.db.get_debates_by_user(g.user['user_id'])
    else:
        debates = extensions.db.get_public_debates()

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


@debate_bp.route('/api/debates', methods=['POST'])
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

    debate = extensions.debate_engine.create_debate(
        resolution=resolution,
        scope=scope
    )
    debate['user_id'] = g.user['user_id']
    extensions.db.save_debate(debate)
    set_session_debate(debate['debate_id'])

    return jsonify({
        'debate_id': debate['debate_id'],
        'resolution': debate['resolution'],
        'scope': debate['scope'],
        'created_at': debate['created_at'],
        'creator': g.user['display_name']
    }), 201


@debate_bp.route('/api/debate', methods=['GET'])
@optional_auth
def get_debate():
    """Get current/active debate"""
    debate_id = get_session_debate_id()

    if not debate_id:
        return jsonify({
            'debate_id': None,
            'resolution': None,
            'scope': None,
            'created_at': None,
            'current_snapshot_id': None,
            'has_debate': False
        })

    debate = extensions.db.get_debate(debate_id)

    if not debate:
        return jsonify({
            'error': 'Debate not found',
            'code': 'DEBATE_NOT_FOUND'
        }), 404

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


@debate_bp.route('/api/debate/<debate_id>', methods=['GET'])
@optional_auth
def get_debate_by_id(debate_id):
    """Get specific debate by ID"""
    if not debate_id or not re.match(r'^[a-zA-Z0-9_-]+$', debate_id):
        raise ValidationError("Invalid debate ID")

    debate = extensions.db.get_debate(debate_id)

    if not debate:
        return jsonify({'error': 'Debate not found'}), 404

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


@debate_bp.route('/api/debate/<debate_id>/activate', methods=['POST'])
@login_required
def activate_debate(debate_id):
    """Set a debate as the user's active debate"""
    if not debate_id or not re.match(r'^[a-zA-Z0-9_-]+$', debate_id):
        raise ValidationError("Invalid debate ID")

    debate = extensions.db.get_debate(debate_id)
    if not debate:
        return jsonify({'error': 'Debate not found'}), 404

    set_session_debate(debate_id)

    return jsonify({
        'message': 'Debate activated',
        'debate_id': debate_id
    })


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------
@debate_bp.route('/api/debate/posts', methods=['POST'])
@login_required
def submit_post():
    """Submit a new post"""
    debate_id = get_session_debate_id()

    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400

    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")

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

    facts = sanitize_html(facts)
    inference = sanitize_html(inference)
    counter_arguments = sanitize_html(counter_arguments)

    post = extensions.debate_engine.submit_post(
        debate_id=debate_id,
        side=side,
        topic_id=topic_id,
        facts=facts,
        inference=inference,
        counter_arguments=counter_arguments
    )
    post['user_id'] = g.user['user_id']
    extensions.db.save_post(post)

    return jsonify({
        'post_id': post['post_id'],
        'side': post['side'],
        'topic_id': post.get('topic_id'),
        'modulation_outcome': post['modulation_outcome'],
        'block_reason': post.get('block_reason'),
        'timestamp': post['timestamp']
    })


@debate_bp.route('/api/debate/posts', methods=['GET'])
@optional_auth
def get_posts():
    """Get posts for current debate"""
    debate_id = get_session_debate_id()

    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400

    posts = extensions.db.get_posts_by_debate(debate_id)

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


# ---------------------------------------------------------------------------
# Frame Petitions (user-facing)
# ---------------------------------------------------------------------------
@debate_bp.route('/api/debate/<debate_id>/frame-petitions', methods=['GET'])
@optional_auth
def list_frame_petitions(debate_id):
    """List public frame petitions for a debate."""
    return jsonify({
        'petitions': extensions.db.get_frame_petitions(debate_id=debate_id),
    })


@debate_bp.route('/api/debate/<debate_id>/frame-petitions', methods=['POST'])
@login_required
def create_frame_petition(debate_id):
    """Submit a candidate frame petition separate from debate proposals."""
    if not extensions.db.get_debate(debate_id):
        return jsonify({'error': 'Debate not found'}), 404
    data = request.get_json() or {}
    candidate = data.get('candidate_frame') or data
    if not isinstance(candidate, dict):
        return jsonify({'error': 'candidate_frame must be an object'}), 400
    petition = extensions.db.create_frame_petition(
        debate_id=debate_id,
        proposer_user_id=g.user['user_id'],
        candidate_frame=candidate,
    )
    extensions.debate_engine.governance.log_change(
        change_type='frame_petition',
        description=f"Frame petition submitted for {debate_id}",
        changed_by=g.user['user_id'],
        justification='Public frame petition intake',
        new_value=petition.get('petition_id'),
    )
    return jsonify({'petition': petition}), 201


# ---------------------------------------------------------------------------
# Debate-scoped incidents
# ---------------------------------------------------------------------------
@debate_bp.route('/api/debate/<debate_id>/incidents', methods=['GET'])
@optional_auth
def get_debate_incidents(debate_id):
    """Get public incidents affecting one debate."""
    all_incidents = extensions.debate_engine.governance.get_incidents(limit=500)
    incidents = [
        incident for incident in all_incidents
        if debate_id in incident.get('affected_debates', [])
    ]
    return jsonify({'debate_id': debate_id, 'incidents': incidents})

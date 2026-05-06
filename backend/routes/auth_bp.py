"""Authentication blueprint — login, register, logout, token refresh."""
import re

from flask import Blueprint, jsonify, request

from backend import extensions
from backend.sanitize import sanitize_html
from backend.utils.decorators import generate_token, login_required
from backend.utils.middleware import set_csrf_cookie
from backend.utils.validators import ValidationError, validate_string

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/auth/register', methods=['POST'])
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
    existing = extensions.db.get_user_by_email(email)
    if existing:
        return jsonify({'error': 'Email already registered', 'code': 'EMAIL_EXISTS'}), 409

    # Create user
    user = extensions.db.create_user(email, password, display_name)

    # Generate token
    token = generate_token(user['user_id'], user['email'], user['display_name'], user.get('is_admin', False))

    response = jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'display_name': user['display_name'],
        'is_admin': user.get('is_admin', False),
        'access_token': token
    })
    response.status_code = 201
    response = set_csrf_cookie(response)
    return response


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """Login user"""
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")

    email = validate_string(data.get('email'), 'Email')
    password = validate_string(data.get('password'), 'Password')

    # Verify credentials
    user = extensions.db.verify_user(email, password)
    if not user:
        return jsonify({'error': 'Invalid credentials', 'code': 'INVALID_CREDENTIALS'}), 401

    # Update last login
    extensions.db.update_last_login(user['user_id'])

    # Generate token
    token = generate_token(user['user_id'], user['email'], user['display_name'], user.get('is_admin', False))

    response = jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'display_name': user['display_name'],
        'is_admin': user.get('is_admin', False),
        'access_token': token
    })
    response = set_csrf_cookie(response)
    return response


@auth_bp.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """Logout user (client should discard token)"""
    # In a more complex system, we might blacklist the token
    response = jsonify({'message': 'Logged out successfully'})
    response = set_csrf_cookie(response)
    return response


@auth_bp.route('/api/auth/me', methods=['GET'])
@login_required
def get_current_user():
    """Get current user info"""
    from flask import g
    return jsonify(g.user)

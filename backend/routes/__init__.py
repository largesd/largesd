"""Flask blueprints for the debate system API."""
from backend.routes.api_bp import api_bp
from backend.routes.auth_bp import auth_bp
from backend.routes.debate_bp import debate_bp
from backend.routes.topic_bp import topic_bp
from backend.routes.snapshot_bp import snapshot_bp
from backend.routes.dossier_bp import dossier_bp
from backend.routes.proposal_bp import proposal_bp
from backend.routes.governance_bp import governance_bp
from backend.routes.admin_bp import admin_bp

__all__ = [
    'api_bp',
    'auth_bp',
    'debate_bp',
    'topic_bp',
    'snapshot_bp',
    'dossier_bp',
    'proposal_bp',
    'governance_bp',
    'admin_bp',
]

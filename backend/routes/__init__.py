"""Flask blueprints for the debate system API."""

from backend.routes.admin_bp import admin_bp
from backend.routes.api_bp import api_bp
from backend.routes.appeals_bp import appeals_bp
from backend.routes.auth_bp import auth_bp
from backend.routes.debate_bp import debate_bp
from backend.routes.dossier_bp import dossier_bp
from backend.routes.frame_bp import frame_bp
from backend.routes.frame_petition_bp import frame_petition_bp
from backend.routes.governance_bp import governance_bp
from backend.routes.judge_bp import judge_bp
from backend.routes.posts_bp import posts_bp
from backend.routes.proposal_bp import proposal_bp
from backend.routes.snapshot_bp import snapshot_bp
from backend.routes.topic_bp import topic_bp

__all__ = [
    "admin_bp",
    "api_bp",
    "appeals_bp",
    "auth_bp",
    "debate_bp",
    "dossier_bp",
    "frame_bp",
    "frame_petition_bp",
    "posts_bp",
    "governance_bp",
    "judge_bp",
    "proposal_bp",
    "snapshot_bp",
    "topic_bp",
]

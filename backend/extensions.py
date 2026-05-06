"""Shared extensions and global state for the debate system.

Initialized by app_v3.create_app(). Blueprints should access these
via attribute lookups (e.g., extensions.debate_engine) so that
module reloads in tests pick up fresh instances.
"""

# Flask app instance
app = None

# Core engine and database
debate_engine = None
db = None

# Async job infrastructure
job_queue = None
job_worker = None

# Rate limiter
limiter = None

# Redis connectivity status (True/False/None)
redis_connected = None

# Runtime profile snapshot
current_runtime_profile = None

# Environment
db_path = "data/debate_system.db"
env = "development"

# Default moderation settings (populated by app factory)
default_moderation_settings = None

"""Shared extensions and global state for the debate system.

Initialized by app_v3.create_app(). Blueprints should access these
via attribute lookups (e.g., extensions.debate_engine) so that
module reloads in tests pick up fresh instances.
"""

from typing import Any

# Flask app instance
app: Any = None

# Core engine and database
debate_engine: Any = None
db: Any = None

# Async job infrastructure
job_queue: Any = None
job_worker: Any = None

# Rate limiter
limiter: Any = None

# Redis connectivity status (True/False/None)
redis_connected: bool | None = None

# Runtime profile snapshot
current_runtime_profile: Any = None

# Environment
db_path: str = "data/debate_system.db"
env: str = "development"

# Default moderation settings (populated by app factory)
default_moderation_settings: Any = None

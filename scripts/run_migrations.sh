#!/bin/bash
# Blind Debate Adjudicator — Database Migration Helper
# Usage: ./scripts/run_migrations.sh [upgrade|downgrade|stamp|status|sql] [revision]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Use venv alembic if available
ALEMBIC="${PROJECT_ROOT}/venv/bin/alembic"
if [ ! -f "$ALEMBIC" ]; then
  ALEMBIC="alembic"
fi

# Default DATABASE_URL if not set
: "${DATABASE_URL:=sqlite:///data/debate_system.db}"

ACTION="${1:-upgrade}"
REVISION="${2:-head}"

cd "$PROJECT_ROOT"

case "$ACTION" in
  upgrade)
    echo "Upgrading to revision: $REVISION"
    DATABASE_URL="$DATABASE_URL" "$ALEMBIC" upgrade "$REVISION"
    ;;
  downgrade)
    echo "Downgrading to revision: $REVISION"
    DATABASE_URL="$DATABASE_URL" "$ALEMBIC" downgrade "$REVISION"
    ;;
  stamp)
    echo "Stamping database at revision: $REVISION"
    DATABASE_URL="$DATABASE_URL" "$ALEMBIC" stamp "$REVISION"
    ;;
  status)
    DATABASE_URL="$DATABASE_URL" "$ALEMBIC" current
    ;;
  sql)
    echo "Generating SQL for upgrade to: $REVISION"
    DATABASE_URL="$DATABASE_URL" "$ALEMBIC" upgrade "$REVISION" --sql
    ;;
  revision)
    if [ -z "$2" ]; then
      echo "Usage: $0 revision 'description of migration'"
      exit 1
    fi
    DATABASE_URL="$DATABASE_URL" "$ALEMBIC" revision -m "$REVISION"
    ;;
  *)
    echo "Usage: $0 [upgrade|downgrade|stamp|status|sql|revision] [revision|message]"
    echo ""
    echo "Examples:"
    echo "  $0 upgrade head           # Upgrade to latest"
    echo "  $0 downgrade -1           # Downgrade one revision"
    echo "  $0 stamp 0cc597040424     # Stamp baseline on existing DB"
    echo "  $0 status                 # Show current revision"
    echo "  $0 sql head               # Generate SQL without executing"
    echo "  $0 revision 'add roles'   # Create new migration"
    exit 1
    ;;
esac

echo "Done."

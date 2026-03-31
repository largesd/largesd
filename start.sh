#!/bin/bash
# Start script for Blind Debate Adjudicator

# Parse arguments
VERSION="1"
while [[ $# -gt 0 ]]; do
    case $1 in
        --v2)
            VERSION="2"
            shift
            ;;
        *)
            break
            ;;
    esac
done

if [ "$VERSION" = "2" ]; then
    echo "============================================================"
    echo "  Blind Debate Adjudicator v2 - Starting Server"
    echo "  (Enhanced with full MSD specification compliance)"
    echo "============================================================"
else
    echo "============================================================"
    echo "  Blind Debate Adjudicator v1 - Starting Server"
    echo "  (Original prototype)"
    echo "============================================================"
fi
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing/updating dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

echo ""

# Start the appropriate server
if [ "$VERSION" = "2" ]; then
    echo "Starting server v2..."
    echo "Features: Span extraction, canonicalization, multi-judge, audits"
    echo ""
    python3 start_server_v2.py "$@"
else
    echo "Starting server v1..."
    echo "Features: Basic scoring, static topics"
    echo ""
    python3 start_server.py "$@"
fi

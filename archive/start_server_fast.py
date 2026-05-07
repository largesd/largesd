#!/usr/bin/env python3
"""
Fast startup script - skips initial snapshot generation
Use this for quick testing of the UI
"""

import argparse
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))


def main():
    parser = argparse.ArgumentParser(description="Blind Debate Adjudicator Server (Fast Start)")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--host", "-H", type=str, default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--skip-debate", action="store_true", help="Skip creating default debate")
    args = parser.parse_args()

    # Set mock mode for speed
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["NUM_JUDGES"] = "3"  # Fewer judges = faster

    print("=" * 60)
    print("Blind Debate Adjudicator - FAST START")
    print("=" * 60)
    print(f"Port: {args.port}")
    print("Mode: Mock (no API calls)")
    print("Note: Create a debate manually in the web UI")
    print("=" * 60)

    # Import and run
    from backend.app_v2 import app

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

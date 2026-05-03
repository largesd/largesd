#!/usr/bin/env python3
"""
Startup script for Blind Debate Adjudicator
Usage: python start_server.py [--port PORT] [--host HOST]
"""
import sys
import os
import argparse

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from backend.app import app, current_debate, debate_engine

def main():
    parser = argparse.ArgumentParser(description='Blind Debate Adjudicator Server')
    parser.add_argument('--port', type=int, default=5000, help='Port to run on (default: 5000)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--fact-mode', type=str, default='ONLINE_ALLOWLIST', 
                       choices=['OFFLINE', 'ONLINE_ALLOWLIST'],
                       help='Fact checking mode (default: ONLINE_ALLOWLIST)')
    args = parser.parse_args()
    
    print("=" * 70)
    print("  Blind Debate Adjudicator - LLM-Adjudicated Debate System")
    print("=" * 70)
    print()
    
    # Initialize debate if not exists
    global current_debate
    if current_debate is None:
        current_debate = debate_engine.create_debate(
            resolution="Resolved: AI should be banned.",
            scope="Whether AI development should be banned and the implications for safety, economics, and society."
        )
    
    # Generate initial snapshot
    debate_engine.generate_snapshot(current_debate.debate_id, "initial")
    
    snapshot = current_debate.current_snapshot
    
    print(f"  Debate ID:        {current_debate.debate_id}")
    print(f"  Resolution:       {current_debate.resolution}")
    print(f"  Fact Check Mode:  {args.fact_mode}")
    print()
    print(f"  Initial Snapshot: {snapshot.snapshot_id}")
    print(f"  Verdict:          {snapshot.verdict}")
    print(f"  Confidence:       {snapshot.confidence:.2f}")
    print(f"  Overall FOR:      {snapshot.overall_for:.2f}")
    print(f"  Overall AGAINST:  {snapshot.overall_against:.2f}")
    print(f"  Margin D:         {snapshot.margin_d:.4f}")
    print()
    print("-" * 70)
    print(f"  Web Interface:    http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}")
    print(f"  API Base:         http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}/api")
    print("-" * 70)
    print()
    print("  Available Pages:")
    print("    • Home:        http://localhost:5000/")
    print("    • New Debate:  http://localhost:5000/new_debate.html")
    print("    • Topics:      http://localhost:5000/topics.html")
    print("    • Verdict:     http://localhost:5000/verdict.html")
    print("    • Audits:      http://localhost:5000/audits.html")
    print("    • Admin:       http://localhost:5000/admin.html")
    print("    • Spec:        http://localhost:5000/about.html")
    print()
    print("=" * 70)
    print("  Press Ctrl+C to stop the server")
    print("=" * 70)
    print()
    
    # Run the Flask app
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)


if __name__ == '__main__':
    main()

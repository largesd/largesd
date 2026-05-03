#!/usr/bin/env python3
"""
Start script for Blind Debate Adjudicator v3
Features:
- Session-based debate management (no global state)
- JWT authentication
- Input validation
- Multi-debate support per user
"""
import os
import sys
import argparse


def describe_configured_model(llm_provider: str) -> str:
    """Return the model or provider detail implied by the current environment."""
    if llm_provider == 'openrouter':
        return os.getenv('OPENROUTER_MODEL', '<unset>')
    if llm_provider == 'openrouter-multi':
        return 'OpenRouter multi-model judge pool'
    if llm_provider == 'openai':
        return os.getenv('OPENAI_MODEL', 'gpt-4')
    return 'mock'


def main():
    parser = argparse.ArgumentParser(description='Blind Debate Adjudicator Server v3')
    parser.add_argument('--port', type=int, default=5000, help='Port to run on (default: 5000)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--db-path', default=os.getenv('DEBATE_DB_PATH', 'data/debate_system.db'),
                       help='SQLite database path (default: data/debate_system.db)')
    parser.add_argument('--fact-mode', default=os.getenv('FACT_CHECK_MODE', 'OFFLINE'),
                       choices=['OFFLINE', 'ONLINE_ALLOWLIST'],
                       help='Fact checking mode (default: $FACT_CHECK_MODE or OFFLINE)')
    parser.add_argument('--llm-provider', default=os.getenv('LLM_PROVIDER', 'mock'),
                       choices=['mock', 'openai', 'openrouter', 'openrouter-multi'],
                       help='LLM provider (default: $LLM_PROVIDER or mock)')
    parser.add_argument('--num-judges', type=int, default=int(os.getenv('NUM_JUDGES', '5')),
                       help='Number of judges for scoring (default: $NUM_JUDGES or 5)')
    
    args = parser.parse_args()
    
    # Set environment variables
    os.environ['DEBATE_DB_PATH'] = args.db_path
    os.environ['FACT_CHECK_MODE'] = args.fact_mode
    os.environ['LLM_PROVIDER'] = args.llm_provider
    os.environ['NUM_JUDGES'] = str(args.num_judges)
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(args.db_path) or '.', exist_ok=True)
    
    print("=" * 70)
    print(" Blind Debate Adjudicator Server v3")
    print("=" * 70)
    print(f" Configuration:")
    print(f"   - Port: {args.port}")
    print(f"   - Host: {args.host}")
    print(f"   - Debug: {args.debug}")
    print(f"   - Database: {args.db_path}")
    print(f"   - Fact Check Mode: {args.fact_mode}")
    print(f"   - LLM Provider: {args.llm_provider}")
    print(f"   - Configured Model: {describe_configured_model(args.llm_provider)}")
    print(f"   - Num Judges: {args.num_judges}")
    print("-" * 70)
    print(" New in v3:")
    print("   ✓ Multi-debate support per user (no global state)")
    print("   ✓ JWT authentication with secure tokens")
    print("   ✓ Input validation and sanitization")
    print("   ✓ Session-based debate management")
    print("   ✓ Dynamic topic pages")
    print("   ✓ localStorage for pending posts")
    print("=" * 70)
    
    # Import and run the v3 app
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
    from app_v3 import app
    
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()

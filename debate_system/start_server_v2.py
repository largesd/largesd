#!/usr/bin/env python3
"""
Startup script for Blind Debate Adjudicator v2
Enhanced version with full MSD specification compliance
"""
import argparse
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def main():
    parser = argparse.ArgumentParser(
        description='Blind Debate Adjudicator Server v2'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=5000,
        help='Port to run the server on (default: 5000)'
    )
    parser.add_argument(
        '--host', '-H',
        type=str,
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--fact-mode',
        type=str,
        choices=['OFFLINE', 'ONLINE_ALLOWLIST'],
        default='OFFLINE',
        help='Fact checking mode (default: OFFLINE)'
    )
    parser.add_argument(
        '--llm-provider',
        type=str,
        choices=['mock', 'openai', 'openrouter', 'openrouter-multi'],
        default='mock',
        help='LLM provider (default: mock)'
    )
    parser.add_argument(
        '--num-judges',
        type=int,
        default=5,
        help='Number of judges for multi-judge evaluation (default: 5)'
    )
    parser.add_argument(
        '--openai-api-key',
        type=str,
        default=os.getenv('OPENAI_API_KEY'),
        help='OpenAI API key (or set OPENAI_API_KEY env var)'
    )
    parser.add_argument(
        '--openrouter-api-key',
        type=str,
        default=os.getenv('OPENROUTER_API_KEY'),
        help='OpenRouter API key (or set OPENROUTER_API_KEY env var)'
    )
    parser.add_argument(
        '--db-path',
        type=str,
        default='data/debate_system.db',
        help='Path to SQLite database (default: data/debate_system.db)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    
    args = parser.parse_args()
    
    # Set environment variables
    os.environ['FACT_CHECK_MODE'] = args.fact_mode
    os.environ['LLM_PROVIDER'] = args.llm_provider
    os.environ['NUM_JUDGES'] = str(args.num_judges)
    
    if args.openai_api_key:
        os.environ['OPENAI_API_KEY'] = args.openai_api_key
    
    if args.openrouter_api_key:
        os.environ['OPENROUTER_API_KEY'] = args.openrouter_api_key
    
    # Print startup info
    print("=" * 70)
    print("Blind Debate Adjudicator Server v2")
    print("=" * 70)
    print(f"Configuration:")
    print(f"  Port:          {args.port}")
    print(f"  Host:          {args.host}")
    print(f"  Fact Mode:     {args.fact_mode}")
    print(f"  LLM Provider:  {args.llm_provider}")
    print(f"  Num Judges:    {args.num_judges}")
    print(f"  Database:      {args.db_path}")
    print(f"  Debug Mode:    {'Enabled' if args.debug else 'Disabled'}")
    print("=" * 70)
    
    if args.llm_provider == 'openai' and not os.getenv('OPENAI_API_KEY'):
        print("WARNING: OpenAI provider selected but no API key found!")
        print("Set OPENAI_API_KEY environment variable or use --openai-api-key")
        print("Falling back to mock provider...")
        os.environ['LLM_PROVIDER'] = 'mock'
    
    if args.llm_provider in ['openrouter', 'openrouter-multi'] and not os.getenv('OPENROUTER_API_KEY'):
        print("WARNING: OpenRouter provider selected but no API key found!")
        print("Set OPENROUTER_API_KEY environment variable or use --openrouter-api-key")
        print("Get a key at: https://openrouter.ai/keys")
        print("Falling back to mock provider...")
        os.environ['LLM_PROVIDER'] = 'mock'
    
    print("\nStarting server...")
    print("-" * 70)
    
    # Import and run the app
    from backend.app_v2 import app, debate_engine, current_debate
    
    # Initialize default debate
    if not current_debate:
        debate_engine.create_debate(
            "Resolved: AI should be banned.",
            "Whether AI development should be banned and the implications for safety, economics, and society."
        )
    
    # Run the Flask app
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=not args.debug  # Disable reloader in debug to avoid double initialization
    )


if __name__ == '__main__':
    main()

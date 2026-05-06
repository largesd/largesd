#!/usr/bin/env python3
"""
Startup script for Blind Debate Adjudicator v3
This is a thin wrapper around start_server_v3.py
"""
# Delegate to v3 server
from start_server_v3 import main

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Startup script for Blind Debate Adjudicator v3
This is a thin wrapper around start_server_v3.py
"""
import sys
import os

# Delegate to v3 server
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from start_server_v3 import main

if __name__ == '__main__':
    main()

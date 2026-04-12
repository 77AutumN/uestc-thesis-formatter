#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Legacy entry point for UESTC Thesis Formatter.
This script has been superseded by scripts/run_v2.py.
For backward compatibility, it now simply forwards all arguments to the new orchestrator.
"""

import os
import sys
import subprocess

def main():
    print("[INFO] run.py is deprecated. Delegating to scripts/run_v2.py...")
    script_path = os.path.join(os.path.dirname(__file__), "scripts", "run_v2.py")
    
    # 强制加上 utf-8 确保控制台不会乱码
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
            
    try:
        result = subprocess.run([sys.executable, script_path] + sys.argv[1:])
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)

if __name__ == "__main__":
    main()

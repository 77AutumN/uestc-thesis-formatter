#!/usr/bin/env python3
"""
run.py — Thesis Formatter 统一入口 (v2 DissertationUESTC 引擎)

代理到 scripts/run_v2.py 的 ThesisFormatterV2 pipeline。
旧 v1 引擎已归档为 run_legacy.py，不再维护。

Usage:
    python run.py thesis.docx --profile uestc-marxism --output-dir ./output/
"""

import os
import sys

# 确保 scripts 目录可被导入
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from run_v2 import main

if __name__ == "__main__":
    main()

"""Shared fixtures for thesis-formatter tests."""
import sys
import os
import pytest

# Add scripts/ to path so we can import pandoc_ast_extract
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

"""WIZCHESS_RULES=small runs the suite on the MicroPython chess rules (esp32/chess.py) instead of python-chess."""
import importlib.util
import os
import sys
from pathlib import Path

collect_ignore = []

if os.environ.get("WIZCHESS_RULES") == "small":
    spec = importlib.util.spec_from_file_location("chess", Path(__file__).parent.parent / "esp32" / "chess.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["chess"] = module
    spec.loader.exec_module(module)
    collect_ignore.append("test_minichess.py")

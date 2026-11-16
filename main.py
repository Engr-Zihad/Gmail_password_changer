"""
main.py
-------
Entry point for the ZIHAD Gmail pw changer desktop app.
Run:  python main.py
"""

import sys
import os

# Set base working directory to executable directory if frozen, else script directory
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)

# ── Dependency check (only when running from source) ───────────────────────────
if not getattr(sys, "frozen", False):
    _MISSING = []
    try:
        import customtkinter
    except ImportError:
        _MISSING.append("customtkinter")
    try:
        import playwright
    except ImportError:
        _MISSING.append("playwright")
    try:
        import requests
    except ImportError:
        _MISSING.append("requests")
    try:
        import pandas
    except ImportError:
        _MISSING.append("pandas")

    if _MISSING:
        print("=" * 60)
        print("ERROR: Missing required packages:")
        for pkg in _MISSING:
            print(f"  • {pkg}")
        print()
        print("Please run the setup commands from SETUP.md first:")
        print("  pip install -r requirements.txt")
        print("  playwright install chrome")
        print("=" * 60)
        sys.exit(1)

# ── Launch GUI ─────────────────────────────────────────────────────────────────
from ui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()

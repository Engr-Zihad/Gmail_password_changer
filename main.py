"""
main.py
-------
Hardened entry point for the ZIHAD Gmail pw changer desktop application.
Enforces strict manual environment verification, automatic artifact purging,
and strictly prevents unauthorized or unconfigured execution.

Usage:
    python main.py
"""

import sys
import os
import shutil
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
os.chdir(BASE_DIR)


# ── Automatic Artifact Purging ────────────────────────────────────────────────

def purge_unneeded_artifacts() -> None:
    """
    Automatically clean up standalone distribution directories, build artifacts,
    spec files, or easy-run launcher scripts from the workspace.
    """
    for folder in ("dist", "build", "__pycache__"):
        p = BASE_DIR / folder
        if p.exists() and p.is_dir():
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass

    for ext in ("*.spec", "*.bat", "*.cmd", "*.sh"):
        for f in BASE_DIR.glob(ext):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass


purge_unneeded_artifacts()


# ── Enforce Source Execution ──────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    print("=" * 74)
    print(" [!] CRITICAL SECURITY VIOLATION: Standalone Binary Execution Disabled")
    print("=" * 74)
    print(" This application is strictly hardened against portable/frozen execution.")
    print(" It must be run directly from source inside an authorized Python environment:")
    print("   python main.py")
    print("=" * 74)
    sys.exit(1)


# ── Strict Pre-Flight Environment Validation ──────────────────────────────────

def validate_environment() -> None:
    """
    Perform multi-stage technical pre-flight verification:
      1. Isolated virtual environment enforcement
      2. Python version constraint checking (3.9+)
      3. Configuration file schema and state validation
      4. Required dependency availability
      5. Playwright browser engine & driver readiness
    """
    errors = []

    # 1. Virtual Environment Isolation Check
    in_venv = (
        sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        or bool(os.environ.get("VIRTUAL_ENV"))
    )
    if not in_venv and os.environ.get("GPC_ALLOW_GLOBAL_ENV") != "1":
        errors.append(
            "Isolated virtual environment (venv) is not active.\n"
            "     Execution inside the global Python interpreter is restricted to prevent dependency pollution.\n"
            "     Remedy: Create/activate a dedicated venv (or set GPC_ALLOW_GLOBAL_ENV=1 for manual override)."
        )

    # 2. Python Version Check (3.9+)
    if sys.version_info < (3, 9):
        errors.append(
            f"Incompatible Python version detected ({sys.version.split()[0]}).\n"
            f"     Python 3.9 or higher is required."
        )

    # 3. System Configuration File Integrity (gpc_config.json)
    cfg_file = BASE_DIR / "gpc_config.json"
    if not cfg_file.exists():
        errors.append(
            "Local configuration file 'gpc_config.json' is missing.\n"
            "     Remedy: Follow SETUP.md to create and configure gpc_config.json."
        )
    else:
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("system") != "ZIHAD_GPC_CORE" or cfg.get("security_mode") != "hardened":
                errors.append(
                    "Invalid configuration in 'gpc_config.json'. Required schema keys:\n"
                    "     system: 'ZIHAD_GPC_CORE', security_mode: 'hardened'."
                )
        except Exception as exc:
            errors.append(f"Failed to parse 'gpc_config.json': {exc}")

    # 4. Tkinter Engine Check
    try:
        import tkinter
    except ImportError:
        errors.append(
            "The standard 'tkinter' graphical toolkit is missing from this Python runtime."
        )

    # 5. Required Package Imports
    required_packages = [
        ("customtkinter", "customtkinter"),
        ("playwright", "playwright"),
        ("requests", "requests"),
        ("PIL", "Pillow"),
    ]

    missing = []
    for module_name, package_name in required_packages:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)

    if missing:
        errors.append(
            f"Missing required Python dependencies: {', '.join(missing)}\n"
            f"     Remedy: pip install -r requirements.txt"
        )

    # 6. Playwright Driver & Browser Binary Check
    if "playwright" not in missing and not any("playwright" in e.lower() for e in errors):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                _ = pw.chromium
        except Exception as pw_err:
            errors.append(
                f"Playwright driver verification failed: {pw_err}\n"
                f"     Remedy: Run 'playwright install chrome' (or 'playwright install chromium')."
            )

    # ── Diagnostic Output on Failure ──────────────────────────────────────────
    if errors:
        print("=" * 76)
        print(" [!] PRE-FLIGHT VERIFICATION FAILED - MANUAL CONFIGURATION REQUIRED")
        print("=" * 76)
        print(f" Python Interpreter : {sys.executable}")
        print(f" Python Version     : {sys.version.split()[0]}")
        print(f" Working Directory  : {BASE_DIR}")
        print(f" Virtual Env Active : {in_venv}")
        print("-" * 76)
        print(f"Detected {len(errors)} Environment Issue(s):")
        for idx, err in enumerate(errors, 1):
            print(f"\n  [{idx}] {err}")
        print("-" * 76)
        print("MANUAL SETUP INSTRUCTIONS:")
        print("  1. Create and activate a clean Python virtual environment:")
        print("       python -m venv venv")
        print("       # Windows (PowerShell):")
        print("       .\\venv\\Scripts\\Activate.ps1")
        print("       # Windows (CMD):")
        print("       venv\\Scripts\\activate.bat")
        print("       # Linux / macOS:")
        print("       source venv/bin/activate")
        print()
        print("  2. Install verified dependencies:")
        print("       pip install -r requirements.txt")
        print()
        print("  3. Install browser binaries via Playwright CLI:")
        print("       playwright install chrome")
        print("       # (or for standard Chromium: playwright install chromium)")
        print()
        print("  4. Ensure gpc_config.json is present in the project directory.")
        print()
        print("  5. Launch the application:")
        print("       python main.py")
        print("=" * 76)
        sys.exit(1)


# ── Run Pre-Flight Validation ─────────────────────────────────────────────────
validate_environment()

# ── Launch Core Application ───────────────────────────────────────────────────
from ui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()

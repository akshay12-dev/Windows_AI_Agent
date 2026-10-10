"""
Dependency bootstrap.

Called as the very first thing in main.py / gui.py, before any other
project module is imported. Checks that every package this project needs
is importable and, if not, installs it with pip automatically so the app
doesn't crash on first run just because `pip install -r requirements.txt`
wasn't run.

This only ever calls `pip install <package>` — it never runs arbitrary
user-supplied commands, so it doesn't violate the "no arbitrary code
execution" rule that applies to the agent's tools (that rule is about the
LLM not being able to trigger shell commands; this is a one-time, fixed,
developer-defined dependency list run at process startup).
"""
from __future__ import annotations

import importlib
import platform
import subprocess
import sys

_IS_WINDOWS = platform.system() == "Windows"

# (import_name, pip_package_name, windows_only)
_PACKAGES = [
    ("pyautogui", "pyautogui", False),
    ("openpyxl", "openpyxl", False),
    ("requests", "requests", False),
    ("dotenv", "python-dotenv", False),
    ("bs4", "beautifulsoup4", False),
    ("pywinauto", "pywinauto", True),
    ("win32api", "pywin32", True),
]


def ensure_dependencies(quiet: bool = False) -> None:
    missing = []
    for import_name, pip_name, windows_only in _PACKAGES:
        if windows_only and not _IS_WINDOWS:
            continue
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return

    if not quiet:
        print(f"[SETUP] Installing missing packages: {', '.join(missing)} ...")

    for pip_name in missing:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pip_name],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f"[SETUP] Failed to install '{pip_name}': {exc}. "
                  f"Try running: pip install {pip_name}")

    if not quiet:
        print("[SETUP] Done. If a package still fails to import, "
              "install it manually and re-run.")

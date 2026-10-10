"""
Windows AI Agent — CLI entry point.

    User -> natural language -> LLM planner -> tool calls -> router -> Windows -> result -> LLM -> User

Run:  python main.py
"""
from __future__ import annotations

import sys

from utils.bootstrap import ensure_dependencies

ensure_dependencies()  # auto-installs any missing packages before other imports

from agent.executor import execute_plan
from agent.llm import LLM
from agent.planner import PlanningError, plan
from agent.router import TOOLS
from utils.logger import log_error

BANNER = """
Windows AI Agent
================
Type a command in plain English. Type 'exit' or 'quit' to leave.
"""


def repl() -> None:
    print(BANNER)
    llm = LLM()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        print()
        try:
            steps = plan(user_input, llm=llm)
        except PlanningError as exc:
            log_error(str(exc))
            continue

        print()
        execute_plan(steps)
        print()


def launch_gui() -> bool:
    """Try to start the GUI. Returns True if it ran (and the process should
    exit after), False if it couldn't start and the caller should fall back
    to the CLI instead."""
    try:
        from gui import CommandBar
    except ImportError as exc:
        print(
            "Could not start the GUI: "
            f"{exc}\n\n"
            "This almost always means your Python install doesn't include "
            "Tcl/Tk (tkinter) — a common gotcha on Windows when the "
            "'tcl/tk and IDLE' option was unchecked during install.\n"
            "Fix: re-run the Python installer, choose 'Modify', and make "
            "sure 'tcl/tk and IDLE' is checked. Or install Python from "
            "python.org / the Microsoft Store, which include it by default.\n\n"
            "Falling back to the command-line interface instead.\n"
        )
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"Could not start the GUI ({exc}). Falling back to the CLI.\n")
        return False

    CommandBar().mainloop()
    return True


if __name__ == "__main__":
    if "--list-tools" in sys.argv:
        for name, spec in TOOLS.items():
            print(f"{name}: {spec['description']}")
        sys.exit(0)

    # GUI is the default. Use --cli to force the terminal interface instead.
    # Automatically falls back to --cli behavior if the GUI can't start
    # (most commonly a Python install missing tkinter/Tcl-Tk).
    if "--cli" not in sys.argv:
        if launch_gui():
            sys.exit(0)
        # fell through: GUI failed to start, run the CLI instead

    repl()

"""
Shared plan-execution logic used by both the CLI (main.py) and the GUI (gui.py).

Features:
- Placeholder resolution for <generated> text/table content.
- Interactive step-by-step progress callbacks (on_step_update).
- Real-time cancellation support (cancel_event / abort flag).
- Session memory updating for files, apps, and clipboard text.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from agent.planner import update_session_memory
from agent.router import dispatch
from utils.logger import log_done, log_error

LogFn = Callable[[str], None]
StepCallback = Callable[[int, int, str, str, dict | None], None]  # (index, total, tool_name, status, result)

PLACEHOLDER = "<generated>"


def _is_placeholder(value: Any) -> bool:
    """True for both forms the LLM might emit for a generated-content
    placeholder: the bare string "<generated>", or a single-item list
    containing it (["<generated>"])."""
    if value == PLACEHOLDER:
        return True
    if isinstance(value, list) and len(value) == 1 and value[0] == PLACEHOLDER:
        return True
    return False


def resolve_arguments(arguments: dict, last_generated_text: Any, last_generated_table: Any) -> dict:
    """Replace any "<generated>" placeholder with real generated content."""
    resolved = {}
    for key, value in arguments.items():
        if _is_placeholder(value):
            if key in ("headers", "rows") and last_generated_table is not None:
                resolved[key] = last_generated_table.get(key)
            elif last_generated_text is not None:
                resolved[key] = last_generated_text
            else:
                resolved[key] = value
        else:
            resolved[key] = value
    return resolved


def execute_plan(
    steps: list[dict],
    log_fn: LogFn | None = None,
    on_step_update: StepCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Run every step in order.

    - Supports cancel_event to cleanly abort mid-flight.
    - on_step_update(step_idx, total_steps, tool_name, status, result) emits:
        status in ('running', 'ok', 'failed', 'cancelled')
    """
    last_generated_text = None
    last_generated_table = None
    total_steps = len(steps)

    for i, step in enumerate(steps, start=1):
        if cancel_event and cancel_event.is_set():
            if log_fn:
                log_fn("[ABORT] Plan cancelled by user.")
            if on_step_update:
                on_step_update(i, total_steps, step["tool"], "cancelled", None)
            return False

        tool_name = step["tool"]
        arguments = resolve_arguments(step["arguments"], last_generated_text, last_generated_table)

        if on_step_update:
            on_step_update(i, total_steps, tool_name, "running", None)

        result = dispatch(tool_name, arguments)

        if log_fn:
            if result.get("success"):
                summary_msg = result.get("message") or result.get("summary") or "ok"
                log_fn(f"[TOOL] {tool_name} -> {summary_msg}")
            else:
                log_fn(f"[TOOL] {tool_name} -> FAILED: {result.get('error')}")

        # Update session memory
        if tool_name == "open_app" and result.get("success"):
            update_session_memory("last_app", arguments.get("app"))
        elif tool_name == "excel_create_table" and result.get("success"):
            update_session_memory("last_file", result.get("path"))
        elif tool_name == "take_screenshot" and result.get("success"):
            update_session_memory("last_file", result.get("path"))

        if tool_name == "generate_text" and result.get("success"):
            last_generated_text = result.get("content")
        elif tool_name == "generate_table" and result.get("success"):
            last_generated_table = {"headers": result.get("headers"), "rows": result.get("rows")}

        if not result.get("success"):
            message = f"Step '{tool_name}' failed: {result.get('error')}. Stopping plan."
            log_error(message)
            if log_fn:
                log_fn(f"[ERROR] {message}")
            if on_step_update:
                on_step_update(i, total_steps, tool_name, "failed", result)
            return False

        if on_step_update:
            on_step_update(i, total_steps, tool_name, "ok", result)

    log_done("Task completed.")
    if log_fn:
        log_fn("[DONE] Task completed.")
    return True

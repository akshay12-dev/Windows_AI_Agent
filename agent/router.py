"""
Tool registry + router.

This is the ONLY surface the LLM can act through. Every entry has a name,
description, argument schema, and the actual callable. The LLM plans against
`TOOLS`'s descriptions (via prompts.build_planner_system) and can never call
anything outside this dict — there is no code-eval path from LLM output to
execution anywhere in this app.
"""
from __future__ import annotations

from tools import apps, clipboard, excel, file_ops, file_search, keyboard, mouse, system, web_search, windows
from utils.logger import log_tool
from utils.validation import ValidationError, require

TOOLS = {
    # --- Windows control ---
    "open_app": {
        "func": windows.open_app,
        "description": "Open a desktop application by name (notepad, excel, chrome).",
        "arguments": {"app": "string", "wait_seconds": "float (optional)"},
    },
    "close_app": {
        "func": windows.close_app,
        "description": "Close a previously opened application by name (notepad, excel, chrome). For File Explorer this closes all Explorer windows and their tabs.",
        "arguments": {"app": "string"},
    },
    "close_windows": {
        "func": windows.close_windows,
        "description": (
            "Close ALL windows/tabs matching a title or process, then verify they closed. "
            "Use match='File Explorer' to close every File Explorer window and all of its tabs. "
            "Use process='notepad.exe' / 'WINWORD.EXE' / 'EXCEL.EXE' to close all open documents "
            "of an app. Use match='<title substring>' for any other window."
        ),
        "arguments": {"match": "string (title substring, optional)", "process": "string (exe name, optional)"},
    },
    "focus_window": {
        "func": windows.focus_window,
        "description": "Bring a window matching the given title substring to the foreground.",
        "arguments": {"title": "string"},
    },
    "list_windows": {
        "func": windows.list_windows,
        "description": "List titles of all currently open windows.",
        "arguments": {},
    },
    "wait_for_window": {
        "func": windows.wait_for_window,
        "description": "Wait until a window matching the given title substring appears.",
        "arguments": {"title": "string", "timeout_seconds": "float (optional)"},
    },
    "read_window": {
        "func": windows.read_window,
        "description": "Read visible text content from a window matching the given title.",
        "arguments": {"title": "string"},
    },
    "take_screenshot": {
        "func": windows.take_screenshot,
        "description": "Take a screenshot and save it to disk.",
        "arguments": {"save_path": "string (optional)"},
    },

    # --- Keyboard / mouse ---
    "type_text": {
        "func": keyboard.type_text,
        "description": "Type text into whichever control currently has focus.",
        "arguments": {"text": "string", "interval": "float (optional)"},
    },
    "press_key": {
        "func": keyboard.press_key,
        "description": "Press a single key (e.g. ENTER, TAB, ESC).",
        "arguments": {"key": "string"},
    },
    "hotkey": {
        "func": keyboard.hotkey,
        "description": "Press a key combination, e.g. ['ctrl', 's'].",
        "arguments": {"keys": "list[string]"},
    },
    "click": {
        "func": mouse.click,
        "description": "Click at fixed screen coordinates. Use only when no control can be located.",
        "arguments": {"x": "int", "y": "int"},
    },
    "double_click": {
        "func": mouse.double_click,
        "description": "Double-click at fixed screen coordinates.",
        "arguments": {"x": "int", "y": "int"},
    },

    # --- Content generation ---
    "generate_text": {
        "func": apps.generate_text,
        "description": "Generate prose content (essay, note, etc.) to later type into an app.",
        "arguments": {"topic": "string", "type": "string (optional, e.g. 'essay')"},
    },
    "generate_table": {
        "func": excel.generate_table,
        "description": "Generate dummy table data (headers + rows) for a given topic.",
        "arguments": {"topic": "string", "row_count": "int (optional, default 10)"},
    },

    # --- Excel ---
    "excel_create_table": {
        "func": excel.excel_create_table,
        "description": "Write headers/rows to a new .xlsx workbook via openpyxl, save it, and open it in Excel.",
        "arguments": {
            "headers": "list[string]",
            "rows": "list[list]",
            "save_path": "string (optional)",
            "sheet_name": "string (optional)",
            "open_after_save": "bool (optional, default true)",
        },
    },
    "excel_append_rows": {
        "func": excel.excel_append_rows,
        "description": "Append rows to an existing .xlsx workbook.",
        "arguments": {"path": "string", "rows": "list[list]", "sheet_name": "string (optional)"},
    },
    "excel_control_live": {
        "func": excel.excel_control_live,
        "description": "Open a live Excel window (pywin32) and type headers/rows into it visibly.",
        "arguments": {"headers": "list[string]", "rows": "list[list]"},
    },

    # --- Web / file search ---
    "search_web": {
        "func": web_search.search_web,
        "description": "Run a structured web search and return title/url/snippet results.",
        "arguments": {"query": "string", "max_results": "int (optional)"},
    },
    "browser_search": {
        "func": web_search.browser_search,
        "description": "Open a browser window to a live search results page for the query.",
        "arguments": {"query": "string", "browser": "string (optional, default 'chrome')"},
    },
    "search_files": {
        "func": file_search.search_files,
        "description": "Search Documents/Downloads/Desktop for files matching a query.",
        "arguments": {"query": "string", "extensions": "list[string] (optional)"},
    },

    # --- Windows System, Audio & OS navigation ---
    "get_system_stats": {
        "func": system.get_system_stats,
        "description": "Get real-time Windows system stats (RAM usage, CPU count, C: drive disk space, battery, active window, OS).",
        "arguments": {},
    },
    "system_control": {
        "func": system.system_control,
        "description": "Control system settings: 'volume_up', 'volume_down', 'mute', 'unmute', 'play_pause', 'next_track', 'prev_track', 'show_desktop', 'lock_screen'.",
        "arguments": {"action": "string"},
    },
    "open_url": {
        "func": system.open_url,
        "description": "Open any web URL in the default web browser (e.g. 'https://youtube.com', 'https://github.com').",
        "arguments": {"url": "string"},
    },
    "minimize_all_windows": {
        "func": windows.minimize_all_windows,
        "description": "Minimize all open windows and show the desktop.",
        "arguments": {},
    },
    "maximize_window": {
        "func": windows.maximize_window,
        "description": "Maximize an open window matching the given title substring.",
        "arguments": {"title": "string"},
    },

    # --- Clipboard ---
    "read_clipboard": {
        "func": clipboard.read_clipboard,
        "description": "Read the current text content from the Windows clipboard.",
        "arguments": {},
    },
    "copy_to_clipboard": {
        "func": clipboard.copy_to_clipboard,
        "description": "Copy text into the Windows clipboard.",
        "arguments": {"text": "string"},
    },

    # --- File Explorer & Safe File Access ---
    "open_folder": {
        "func": file_ops.open_folder,
        "description": "Open a folder in Windows File Explorer ('downloads', 'documents', 'desktop', or a custom path).",
        "arguments": {"folder": "string (optional, default 'downloads')"},
    },
    "create_folder": {
        "func": file_ops.create_folder,
        "description": (
            "Create one or more new folders. Leave 'path' empty to create them in the folder "
            "currently open in File Explorer. Naming is Windows-style "
            "('New folder', 'New folder (2)', ...) unless 'name' is given."
        ),
        "arguments": {
            "name": "string (optional, default 'New folder')",
            "count": "int (optional, default 1)",
            "path": "string (optional target directory)",
        },
    },
    "read_file": {
        "func": file_ops.read_file,
        "description": "Safely read text from a local file (e.g. .txt, .py, .md, .csv, .json).",
        "arguments": {"path": "string", "max_chars": "int (optional, default 4000)"},
    },
}


def dispatch(tool_name: str, arguments: dict) -> dict:
    """Run a single tool call. Every registered tool runs unconditionally —
    the agent has full access, there is no confirmation gate."""
    spec = TOOLS.get(tool_name)
    if spec is None:
        return {"success": False, "error": f"Unknown tool '{tool_name}' — not in registry"}

    try:
        result = spec["func"](**arguments)
    except ValidationError as exc:
        result = {"success": False, "error": str(exc)}
    except TypeError as exc:
        result = {"success": False, "error": f"Bad arguments for '{tool_name}': {exc}"}
    except Exception as exc:  # noqa: BLE001 - tool errors must never crash the agent
        result = {"success": False, "error": f"'{tool_name}' raised an exception: {exc}"}

    status = "success" if result.get("success") else "failed"
    log_tool(f"{tool_name} -> {status}" + ("" if result.get("success") else f" ({result.get('error')})"))
    return result

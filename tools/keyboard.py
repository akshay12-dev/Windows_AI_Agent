"""Keyboard tools. pyautogui is the fallback layer described in the spec —
used for typing/keys once a target window/control is focused."""
from __future__ import annotations

import platform

_IS_WINDOWS = platform.system() == "Windows"
_PYAUTOGUI_AVAILABLE = False
_IMPORT_ERROR = None

try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
except ImportError as exc:
    _IMPORT_ERROR = exc


def _not_windows_result(tool_name: str) -> dict:
    if not _PYAUTOGUI_AVAILABLE:
        return {
            "success": False,
            "error": f"{tool_name} requires pyautogui, which failed to import ({_IMPORT_ERROR}). Run: pip install pyautogui",
        }
    return {
        "success": False,
        "error": f"{tool_name} requires Windows. This process is running on {platform.system()}.",
    }


def type_text(text: str, interval: float = 0.01) -> dict:
    if not _PYAUTOGUI_AVAILABLE:
        return _not_windows_result("type_text")
    try:
        pyautogui.write(text, interval=interval)
        return {"success": True, "message": f"Typed {len(text)} characters"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def press_key(key: str) -> dict:
    if not _PYAUTOGUI_AVAILABLE:
        return _not_windows_result("press_key")
    try:
        pyautogui.press(key.lower())
        return {"success": True, "message": f"Pressed {key}"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def hotkey(keys: list[str]) -> dict:
    if not _PYAUTOGUI_AVAILABLE:
        return _not_windows_result("hotkey")
    try:
        pyautogui.hotkey(*[k.lower() for k in keys])
        return {"success": True, "message": f"Pressed hotkey {'+'.join(keys)}"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}

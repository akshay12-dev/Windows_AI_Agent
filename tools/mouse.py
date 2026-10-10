"""Mouse tools. Prefer control-based clicking via pywinauto where possible;
these raw x/y tools are the pyautogui fallback for cases with no accessible
control (per spec: don't rely exclusively on fixed coordinates)."""
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


def click(x: int, y: int) -> dict:
    if not _PYAUTOGUI_AVAILABLE:
        return _not_windows_result("click")
    try:
        pyautogui.click(x, y)
        return {"success": True, "message": f"Clicked at ({x}, {y})"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def double_click(x: int, y: int) -> dict:
    if not _PYAUTOGUI_AVAILABLE:
        return _not_windows_result("double_click")
    try:
        pyautogui.doubleClick(x, y)
        return {"success": True, "message": f"Double-clicked at ({x}, {y})"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}

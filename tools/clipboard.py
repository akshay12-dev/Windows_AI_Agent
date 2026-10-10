"""
Windows Clipboard tools.
Allows the agent to read whatever text is currently copied to the user's
clipboard, or copy text into the clipboard for immediate pasting.
"""
from __future__ import annotations

from typing import Any


def read_clipboard() -> dict[str, Any]:
    """Read the current text content from the Windows clipboard."""
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return {"success": True, "text": "", "message": "Clipboard is empty"}
        preview = text[:120] + "..." if len(text) > 120 else text
        return {"success": True, "text": text, "message": f"Read clipboard: '{preview}'"}
    except Exception as exc:
        return {"success": False, "error": f"Failed to read clipboard: {exc}"}


def copy_to_clipboard(text: str) -> dict[str, Any]:
    """Copy the given text into the Windows clipboard."""
    try:
        import pyperclip
        pyperclip.copy(text)
        preview = text[:80] + "..." if len(text) > 80 else text
        return {"success": True, "message": f"Copied to clipboard: '{preview}'"}
    except Exception as exc:
        return {"success": False, "error": f"Failed to write to clipboard: {exc}"}

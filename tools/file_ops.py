"""
Safe File Operations: opening/creating folders in File Explorer and
previewing files.
"""
from __future__ import annotations

import ctypes
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from config import Config

_IS_WINDOWS = platform.system() == "Windows"


def _resolve_folder(folder_name: str) -> Path:
    f_lower = folder_name.strip().lower()
    home = Path.home()
    if f_lower in ("downloads", "download"):
        return home / "Downloads"
    if f_lower in ("documents", "document", "docs", "doc"):
        return home / "Documents"
    if f_lower in ("desktop", "desk"):
        return home / "Desktop"
    if f_lower in ("pictures", "photos"):
        return home / "Pictures"
    if f_lower in ("music",):
        return home / "Music"
    if f_lower in ("videos",):
        return home / "Videos"

    p = Path(os.path.expandvars(os.path.expanduser(folder_name.strip())))
    return p if p.is_absolute() else home / p


def open_folder(folder: str = "downloads") -> dict[str, Any]:
    """Open a folder (e.g. 'downloads', 'documents', 'desktop', or a custom path) in Windows File Explorer."""
    path = _resolve_folder(folder)
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"success": False, "error": f"Folder '{folder}' does not exist and could not be created: {exc}"}

    try:
        if _IS_WINDOWS:
            os.startfile(str(path))
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
        return {"success": True, "message": f"Opened folder '{path}' in File Explorer", "path": str(path)}
    except Exception as exc:
        return {"success": False, "error": f"Could not open folder '{path}': {exc}"}


def _url_to_path(url: str) -> Path | None:
    """Convert a Shell LocationURL (file:///C:/Users/...) to a Path."""
    if not url or not url.lower().startswith("file:"):
        return None
    try:
        path = unquote(urlparse(url).path)
    except Exception:
        return None
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]  # strip the leading slash of /C:/...
    path = path.replace("/", os.sep)
    return Path(path) if path else None


def current_explorer_folder() -> Path | None:
    """Return the folder shown by the active (or most recent) File Explorer
    window, or None if no Explorer window is open."""
    if not _IS_WINDOWS:
        return None
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
    except Exception:
        return None

    try:
        foreground = ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        foreground = 0

    fallback = None
    try:
        windows = shell.Windows()
    except Exception:
        return None

    for window in windows:
        try:
            full_name = str(window.FullName or "").lower()
            if "explorer.exe" not in full_name:
                continue
            folder = _url_to_path(str(window.LocationURL or ""))
            if folder is None or not folder.exists():
                continue
            try:
                hwnd = int(window.HWND)
            except Exception:
                hwnd = 0
            if hwnd and hwnd == foreground:
                return folder
            fallback = folder
        except Exception:
            continue
    return fallback


def _resolve_target_dir(path: str) -> Path:
    """Explicit path wins; otherwise use the folder open in File Explorer;
    otherwise fall back to the Desktop."""
    if path and path.strip():
        return _resolve_folder(path)

    explorer_folder = current_explorer_folder()
    if explorer_folder is not None:
        return explorer_folder

    desktop = Path.home() / "Desktop"
    return desktop if desktop.exists() else Path.home()


def _unique_folder(base_dir: Path, name: str) -> Path:
    """Windows Explorer-style naming: 'Reports', 'Reports (2)', 'Reports (3)'..."""
    clean = re.sub(r'[<>:"/\\|?*]', "", (name or "").strip()).strip() or "New folder"
    candidate = base_dir / clean
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = base_dir / f"{clean} ({index})"
        if not candidate.exists():
            return candidate
        index += 1


def create_folder(name: str = "New folder", count: int = 1, path: str = "") -> dict[str, Any]:
    """Create one or more folders. If `path` is omitted, they are created in
    the folder currently open in File Explorer. Windows-style names are used
    ('New folder', 'New folder (2)', ...)."""
    try:
        count = max(1, min(int(count), 500))
    except (TypeError, ValueError):
        count = 1

    base_dir = _resolve_target_dir(path)
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"success": False, "error": f"Cannot use target directory '{base_dir}': {exc}"}

    created: list[str] = []
    for _ in range(count):
        target = _unique_folder(base_dir, name)
        try:
            target.mkdir()
        except OSError as exc:
            return {
                "success": False,
                "error": f"Failed to create folder in '{base_dir}': {exc}",
                "created": created,
            }
        created.append(str(target))

    return {
        "success": True,
        "path": str(base_dir),
        "created": created,
        "message": f"Created {len(created)} folder(s) in '{base_dir}'",
    }


def read_file(path: str, max_chars: int = 4000) -> dict[str, Any]:
    """
    Safely read text from a local file (e.g. .txt, .py, .md, .csv, .json, .log).
    Limits to max_chars characters to prevent memory blowups.
    """
    p = Path(os.path.expandvars(os.path.expanduser(path.strip())))
    if not p.is_absolute():
        # Check Documents, Desktop, Downloads, or current dir
        found = None
        for candidate in [Path.cwd() / p, Path.home() / "Documents" / p, Path.home() / "Desktop" / p, Path.home() / "Downloads" / p]:
            if candidate.is_file():
                found = candidate
                break
        if found:
            p = found
        else:
            return {"success": False, "error": f"File '{path}' not found."}

    if not p.is_file():
        return {"success": False, "error": f"'{p}' is not a file."}

    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        truncated = len(content) >= max_chars
        msg = f"Read {len(content)} characters from '{p.name}'" + (" (truncated)" if truncated else "")
        return {
            "success": True,
            "path": str(p),
            "content": content,
            "truncated": truncated,
            "message": msg,
        }
    except Exception as exc:
        return {"success": False, "error": f"Failed to read file '{p}': {exc}"}

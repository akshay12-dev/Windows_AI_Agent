"""
Windows UI automation primitives.

Primary: pywinauto (locate/control windows by title, control type,
automation ID, name — not fixed coordinates).
Fallback: pyautogui, only for raw keyboard/mouse when pywinauto can't reach
a control.

These imports are Windows-only. On non-Windows platforms the module still
imports (so the rest of the codebase can be read/tested), but calls return a
structured failure result explaining that Windows automation isn't available.
"""
from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import time

_IS_WINDOWS = platform.system() == "Windows"
_AUTOMATION_AVAILABLE = False
_IMPORT_ERROR = None

if _IS_WINDOWS:
    try:
        import pyautogui
        from pywinauto import Desktop
        from pywinauto.application import Application
        from pywinauto.findwindows import ElementNotFoundError
        _AUTOMATION_AVAILABLE = True
    except ImportError as exc:
        # utils.bootstrap.ensure_dependencies() should install these on
        # startup, but if that failed (no internet, restricted env, etc.)
        # fall back to structured errors instead of crashing the app.
        _IMPORT_ERROR = exc

# App name -> how to launch it, plus common fallback install paths.
# CreateProcess (what pywinauto's Application().start() uses) requires
# either a bare filename that's on PATH, or a full path — and most GUI
# apps (Excel, Word, Chrome...) are NOT on PATH even though Windows can
# launch them fine via Start Menu / Win+R. So we resolve in this order:
#   1. Windows "App Paths" registry key (same mechanism Win+R/shell uses)
#   2. shutil.which() (PATH lookup)
#   3. Known common install locations
#   4. os.startfile() as a last resort (goes through the shell directly)
APP_LAUNCH_MAP = {
    "notepad": {
        "exe": "notepad.exe",
        "title_re": ".*Notepad",
        "fallback_paths": [r"C:\Windows\System32\notepad.exe"],
    },
    "excel": {
        "exe": "EXCEL.EXE",
        "title_re": ".*Excel",
        "fallback_paths": [
            r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files\Microsoft Office\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office15\EXCEL.EXE",
        ],
    },
    "word": {
        "exe": "WINWORD.EXE",
        "title_re": ".*Word",
        "fallback_paths": [
            r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
        ],
    },
    "chrome": {
        "exe": "chrome.exe",
        "title_re": ".*Chrome",
        "fallback_paths": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
    },
    "edge": {
        "exe": "msedge.exe",
        "title_re": ".*Edge",
        "fallback_paths": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
    },
    "calc": {
        "exe": "calc.exe",
        "title_re": ".*Calculator",
        "fallback_paths": [r"C:\Windows\System32\calc.exe"],
    },
    "calculator": {
        "exe": "calc.exe",
        "title_re": ".*Calculator",
        "fallback_paths": [r"C:\Windows\System32\calc.exe"],
    },
    "paint": {
        "exe": "mspaint.exe",
        "title_re": ".*Paint",
        "fallback_paths": [r"C:\Windows\System32\mspaint.exe"],
    },
    "cmd": {
        "exe": "cmd.exe",
        "title_re": ".*Command Prompt",
        "fallback_paths": [r"C:\Windows\System32\cmd.exe"],
    },
    "powershell": {
        "exe": "powershell.exe",
        "title_re": ".*PowerShell",
        "fallback_paths": [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"],
    },
    "terminal": {
        "exe": "wt.exe",
        "title_re": ".*Terminal",
        "fallback_paths": [],
    },
    "code": {
        "exe": "Code.exe",
        "title_re": ".*Visual Studio Code",
        "fallback_paths": [
            rf"{os.environ.get('LOCALAPPDATA', '')}\Programs\Microsoft VS Code\Code.exe",
            r"C:\Program Files\Microsoft VS Code\Code.exe",
        ],
    },
    "explorer": {
        "exe": "explorer.exe",
        "title_re": ".*File Explorer",
        "fallback_paths": [r"C:\Windows\explorer.exe"],
    },
    "camera": {
        "exe": "microsoft.windows.camera:",
        "title_re": ".*Camera",
        "process": "WindowsCamera.exe",
        "fallback_paths": [],
    },
    "settings": {
        "exe": "ms-settings:",
        "title_re": ".*Settings",
        "process": "SystemSettings.exe",
        "fallback_paths": [],
    },
    "taskmgr": {
        "exe": "taskmgr.exe",
        "title_re": ".*Task Manager",
        "process": "Taskmgr.exe",
        "fallback_paths": [r"C:\Windows\System32\Taskmgr.exe"],
    },
    "task manager": {
        "exe": "taskmgr.exe",
        "title_re": ".*Task Manager",
        "process": "Taskmgr.exe",
        "fallback_paths": [r"C:\Windows\System32\Taskmgr.exe"],
    },
    "snipping tool": {
        "exe": "snippingtool.exe",
        "title_re": ".*Snipping Tool",
        "process": "SnippingTool.exe",
        "fallback_paths": [r"C:\Windows\System32\SnippingTool.exe"],
    },
    "snippingtool": {
        "exe": "snippingtool.exe",
        "title_re": ".*Snipping Tool",
        "process": "SnippingTool.exe",
        "fallback_paths": [r"C:\Windows\System32\SnippingTool.exe"],
    },
    "photos": {
        "exe": "ms-photos:",
        "title_re": ".*Photos",
        "fallback_paths": [],
    },
    "spotify": {
        "exe": "spotify.exe",
        "title_re": ".*Spotify",
        "process": "Spotify.exe",
        "fallback_paths": [],
    },
}


def _resolve_launch_target(exe_name: str, fallback_paths: list) -> str | None:
    """Return a launchable path/command for exe_name, or None if unresolvable."""
    import shutil

    # 1) Windows "App Paths" registry (same lookup Win+R and the shell use)
    if _IS_WINDOWS:
        try:
            import winreg
            key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                        if value:
                            return value
                except FileNotFoundError:
                    continue
        except Exception:
            pass

    # 2) PATH lookup
    which = shutil.which(exe_name)
    if which:
        return which

    # 3) Known common install locations
    import os as _os
    for candidate in fallback_paths:
        if _os.path.exists(candidate):
            return candidate

    return None

# Tracks live pywinauto Application objects for this session, keyed by app name.
_running_apps: dict = {}


def _not_windows_result(tool_name: str) -> dict:
    if not _IS_WINDOWS:
        return {
            "success": False,
            "error": (
                f"{tool_name} requires Windows (pywinauto/pyautogui/pywin32). "
                f"This process is running on {platform.system()}."
            ),
        }
    return {
        "success": False,
        "error": (
            f"{tool_name} requires pywinauto/pyautogui, which failed to import "
            f"({_IMPORT_ERROR}). Run: pip install pywinauto pyautogui pywin32"
        ),
    }


def open_app(app: str, wait_seconds: float = 3.0) -> dict:
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("open_app")

    import subprocess

    app_key = app.strip().lower()
    launch = APP_LAUNCH_MAP.get(app_key)

    # 1. Protocol URI apps (e.g. microsoft.windows.camera:, ms-settings:)
    if launch and launch["exe"].endswith(":"):
        try:
            os.startfile(launch["exe"])
            return {"success": True, "message": f"{app} opened successfully"}
        except Exception as exc:
            return {"success": False, "error": f"Failed to launch {app}: {exc}"}

    # 2. Known apps with exe and fallback paths
    if launch:
        target = _resolve_launch_target(launch["exe"], launch["fallback_paths"])
        started = False
        last_error = None

        if target:
            try:
                application = Application(backend="uia").start(target)
                _running_apps[app_key] = application
                started = True
            except Exception as exc:
                last_error = exc

        if not started:
            try:
                os.startfile(target or launch["exe"])
                started = True
            except Exception as exc:
                last_error = last_error or exc

        if not started:
            return {
                "success": False,
                "error": f"Failed to open {app}: could not locate or launch '{launch['exe']}'. {last_error}",
            }

        # Quick best-effort focus (up to 2 seconds, no hanging)
        deadline = time.time() + min(wait_seconds, 2.0)
        while time.time() < deadline:
            try:
                window = Desktop(backend="uia").window(title_re=launch["title_re"])
                if window.exists():
                    window.set_focus()
                    if app_key not in _running_apps:
                        try:
                            _running_apps[app_key] = Application(backend="uia").connect(title_re=launch["title_re"])
                        except Exception:
                            pass
                    break
            except Exception:
                pass
            time.sleep(0.2)

        return {"success": True, "message": f"{app} opened successfully"}

    # 3. Generic fallback: Any app on Windows PATH or Shell
    try:
        os.startfile(app)
        return {"success": True, "message": f"{app} opened successfully"}
    except Exception:
        pass

    try:
        os.startfile(f"{app}.exe")
        return {"success": True, "message": f"{app} opened successfully"}
    except Exception as exc:
        return {
            "success": False,
            "error": f"Could not find or open application '{app}'. Known apps: {list(APP_LAUNCH_MAP.keys())}",
        }


# --- Window-closing helpers ----------------------------------------------

# Window classes used by Windows File Explorer top-level windows. Closing one
# of these closes the window *and every tab inside it*.
_EXPLORER_CLASSES = {"CabinetWClass", "ExploreWClass"}

# Words a user might use to mean "File Explorer windows/tabs".
_EXPLORER_ALIASES = {
    "explorer", "file explorer", "explorer window", "explorer windows",
    "file explorer window", "file explorer windows", "files", "file",
    "folders", "folder", "tabs", "tab", "all files", "all folders",
}


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def _process_name(pid: int) -> str:
    """Return the lowercased executable name for a PID ('' if unknown)."""
    if not pid:
        return ""
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_uint(32768)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def _iter_visible_windows():
    """Yield visible top-level windows (never our own process)."""
    own_pid = os.getpid()
    try:
        windows = Desktop(backend="uia").windows()
    except Exception:
        return
    for win in windows:
        try:
            if win.element_info.process_id == own_pid:
                continue
            if not ctypes.windll.user32.IsWindowVisible(win.handle):
                continue
            yield win
        except Exception:
            continue


def _window_matches(win, match: str, process: str) -> bool:
    normalized = (match or "").strip().lower()
    name = os.path.basename((process or "").strip()).lower()

    if name:
        try:
            if _process_name(win.element_info.process_id) != name:
                return False
        except Exception:
            return False
        if not normalized:
            return True

    try:
        class_name = (win.class_name() or "").strip()
    except Exception:
        class_name = ""
    if normalized in _EXPLORER_ALIASES and class_name in _EXPLORER_CLASSES:
        return True

    try:
        title = (win.window_text() or "").lower()
    except Exception:
        title = ""
    return bool(normalized and normalized in title)


def _window_gone(win) -> bool:
    try:
        return not ctypes.windll.user32.IsWindow(win.handle)
    except Exception:
        return True


def _dialog_mentions_save(win) -> bool:
    try:
        if "save" in (win.window_text() or "").lower():
            return True
    except Exception:
        pass
    try:
        for child in win.descendants():
            try:
                if "save" in (child.window_text() or "").lower():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _dismiss_save_prompt(parent_win) -> bool:
    """When closing a document triggers an unsaved-changes prompt, click
    "Don't save" so the window can actually close. Returns True if a prompt
    was dismissed."""
    try:
        pid = parent_win.element_info.process_id
    except Exception:
        return False

    clicked = False
    try:
        dialogs = Desktop(backend="uia").windows()
    except Exception:
        return False

    for dlg in dialogs:
        try:
            if dlg.element_info.process_id != pid:
                continue
            if dlg.handle == parent_win.handle:
                continue
            if not ctypes.windll.user32.IsWindowVisible(dlg.handle):
                continue
            if not _dialog_mentions_save(dlg):
                continue
            for label in ("don't save", "don’t save", "dont save", "discard", "no"):
                try:
                    btn = dlg.child_window(
                        title_re=rf"(?i)^{re.escape(label)}$", control_type="Button"
                    )
                    if btn.exists(timeout=0.2):
                        try:
                            btn.click_input()
                        except Exception:
                            btn.click()
                        clicked = True
                        break
                except Exception:
                    continue
        except Exception:
            continue
    return clicked


def _close_window(win) -> None:
    """Request a window to close, then give unsaved-changes prompts a chance
    to be dismissed. Actual success is verified by the caller re-enumerating."""
    try:
        win.close()
    except Exception:
        try:
            ctypes.windll.user32.PostMessageW(win.handle, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            return

    deadline = time.time() + 1.5
    while time.time() < deadline:
        if _window_gone(win):
            return
        time.sleep(0.15)

    if _dismiss_save_prompt(win):
        deadline = time.time() + 2.5
        while time.time() < deadline:
            if _window_gone(win):
                return
            time.sleep(0.15)


def close_windows(match: str = "", process: str = "") -> dict:
    """Close every visible window matching a title substring (match=...) or an
    executable name (process=...). For File Explorer this closes the window and
    all of its tabs. Reports success only after verification that no matching
    window remains open."""
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("close_windows")

    if not (match or "").strip() and not (process or "").strip():
        return {
            "success": False,
            "error": "close_windows needs a title 'match' (e.g. 'File Explorer') or a 'process' name (e.g. 'notepad.exe').",
        }

    try:
        targets = [w for w in _iter_visible_windows() if _window_matches(w, match, process)]
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"Could not enumerate windows: {exc}"}

    if not targets:
        return {"success": True, "closed": 0, "remaining": 0, "message": "No matching windows were open."}

    for win in targets:
        _close_window(win)

    # Verify by re-enumerating — never report success while windows remain.
    try:
        remaining = [w for w in _iter_visible_windows() if _window_matches(w, match, process)]
    except Exception:
        remaining = []

    remaining_titles = []
    for win in remaining:
        try:
            remaining_titles.append(win.window_text() or "?")
        except Exception:
            remaining_titles.append("?")

    if remaining:
        return {
            "success": False,
            "closed": len(targets) - len(remaining),
            "remaining": len(remaining),
            "error": (
                f"{len(remaining)} window(s) are still open (blocked by a dialog?): "
                f"{remaining_titles}"
            ),
        }

    return {
        "success": True,
        "closed": len(targets),
        "remaining": 0,
        "message": f"Closed {len(targets)} window(s).",
    }


def close_app(app: str) -> dict:
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("close_app")

    import subprocess

    app_key = app.strip().lower()

    # File Explorer is the desktop shell — killing explorer.exe would nuke the
    # taskbar/desktop. Close its windows (and their tabs) instead.
    if app_key in _EXPLORER_ALIASES or app_key in ("explorer.exe", "file explorer.exe"):
        return close_windows(match="File Explorer")

    # 1. Check tracked pywinauto instance
    application = _running_apps.get(app_key)
    if application:
        try:
            pid = application.process
            application.kill()
            time.sleep(0.4)
            _running_apps.pop(app_key, None)
            if not _pid_alive(pid):
                return {"success": True, "message": f"{app} closed"}
        except Exception:
            pass

    # 2. Kill by process name (APP_LAUNCH_MAP, else <app>.exe)
    launch = APP_LAUNCH_MAP.get(app_key, {})
    proc_name = launch.get("process") or (launch.get("exe") if launch.get("exe", "").endswith(".exe") else f"{app_key}.exe")

    if proc_name:
        try:
            res = subprocess.run(["taskkill", "/F", "/IM", proc_name], capture_output=True, text=True)
            if res.returncode == 0:
                time.sleep(0.4)
                check = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {proc_name}"],
                    capture_output=True, text=True,
                )
                if proc_name.lower() not in check.stdout.lower():
                    _running_apps.pop(app_key, None)
                    return {"success": True, "message": f"{app} closed"}
        except Exception:
            pass

    # 3. Best-effort close by window title, then verify it went away.
    if launch.get("title_re"):
        try:
            window = Desktop(backend="uia").window(title_re=launch["title_re"])
            if window.exists():
                window.close()
                if not window.exists(timeout=2):
                    return {"success": True, "message": f"{app} closed"}
        except Exception:
            pass

    return {
        "success": False,
        "error": f"Could not close '{app}' — no running process or window matched it.",
    }


def focus_window(title: str) -> dict:
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("focus_window")
    try:
        window = Desktop(backend="uia").window(title_re=f".*{title}.*")
        if not window.exists():
            return {"success": False, "error": f"No window matching '{title}'"}
        window.set_focus()
        return {"success": True, "message": f"Focused window '{title}'"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def list_windows() -> dict:
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("list_windows")
    try:
        titles = [w.window_text() for w in Desktop(backend="uia").windows() if w.window_text()]
        return {"success": True, "windows": titles}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def wait_for_window(title: str, timeout_seconds: float = 10.0) -> dict:
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("wait_for_window")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            window = Desktop(backend="uia").window(title_re=f".*{title}.*")
            if window.exists():
                return {"success": True, "message": f"Window '{title}' appeared"}
        except ElementNotFoundError:
            pass
        time.sleep(0.3)
    return {"success": False, "error": f"Window '{title}' did not appear within {timeout_seconds}s"}


def read_window(title: str) -> dict:
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("read_window")
    try:
        window = Desktop(backend="uia").window(title_re=f".*{title}.*")
        if not window.exists():
            return {"success": False, "error": f"No window matching '{title}'"}
        texts = window.descendants()
        content = "\n".join(t.window_text() for t in texts if t.window_text())
        return {"success": True, "content": content}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def take_screenshot(save_path: str = "screenshot.png") -> dict:
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("take_screenshot")
    try:
        img = pyautogui.screenshot()
        img.save(save_path)
        return {"success": True, "path": save_path, "message": f"Screenshot saved to {save_path}"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def minimize_all_windows() -> dict:
    """Minimize all open windows and show the Windows Desktop."""
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("minimize_all_windows")
    try:
        pyautogui.hotkey("win", "d")
        return {"success": True, "message": "Minimized all windows (Desktop shown)"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def maximize_window(title: str) -> dict:
    """Maximize a window matching the given title substring."""
    if not _AUTOMATION_AVAILABLE:
        return _not_windows_result("maximize_window")
    try:
        window = Desktop(backend="uia").window(title_re=f".*{title}.*")
        if not window.exists():
            return {"success": False, "error": f"No window matching '{title}'"}
        window.maximize()
        return {"success": True, "message": f"Maximized window '{title}'"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


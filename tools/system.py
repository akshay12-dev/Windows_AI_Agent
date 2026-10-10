"""
Windows system monitoring, audio/media controls, and OS navigation tools.

Uses native Windows APIs (kernel32, user32) and Python standard libraries
without requiring heavy external dependencies.
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import time
import urllib.parse
import webbrowser
from typing import Any

_IS_WINDOWS = platform.system() == "Windows"


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def get_system_stats() -> dict[str, Any]:
    """
    Get live system stats: RAM usage, free disk space, battery status,
    screen resolution, operating system version, and active window.
    """
    stats: dict[str, Any] = {
        "os": f"Windows {platform.release()} ({platform.version()})",
        "cpu_count": os.cpu_count() or 1,
    }

    if not _IS_WINDOWS:
        return {"success": True, "stats": stats, "summary": "Running on non-Windows platform"}

    # 1. RAM Usage
    try:
        mem = _MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            total_gb = round(mem.ullTotalPhys / (1024**3), 1)
            used_gb = round((mem.ullTotalPhys - mem.ullAvailPhys) / (1024**3), 1)
            stats["ram"] = {
                "used_gb": used_gb,
                "total_gb": total_gb,
                "percent": mem.dwMemoryLoad,
            }
    except Exception:
        pass

    # 2. Disk Usage (C: drive)
    try:
        disk = shutil.disk_usage("C:")
        stats["disk_c"] = {
            "free_gb": round(disk.free / (1024**3), 1),
            "total_gb": round(disk.total / (1024**3), 1),
            "used_percent": round((disk.used / disk.total) * 100, 1),
        }
    except Exception:
        pass

    # 3. Battery status
    try:
        sps = _SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            pct = int(sps.BatteryLifePercent)
            if pct <= 100:
                stats["battery"] = {
                    "percent": pct,
                    "charging": sps.ACLineStatus == 1,
                }
    except Exception:
        pass

    # 4. Display & Active Window
    try:
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        stats["screen"] = f"{sw}x{sh}"

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        stats["active_window"] = buff.value or "Desktop"
    except Exception:
        pass

    # Formatted human-readable summary
    summary_parts = []
    if "ram" in stats:
        summary_parts.append(f"RAM: {stats['ram']['used_gb']}/{stats['ram']['total_gb']} GB ({stats['ram']['percent']}%)")
    if "disk_c" in stats:
        summary_parts.append(f"Disk C: {stats['disk_c']['free_gb']} GB free of {stats['disk_c']['total_gb']} GB")
    if "battery" in stats:
        charging_str = "charging" if stats["battery"]["charging"] else "on battery"
        summary_parts.append(f"Battery: {stats['battery']['percent']}% ({charging_str})")
    if "active_window" in stats:
        summary_parts.append(f"Active Window: '{stats['active_window']}'")

    summary = " | ".join(summary_parts)
    return {"success": True, "stats": stats, "summary": summary}


# Windows Virtual Key Codes
_VK_VOLUME_MUTE = 0xAD
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_UP = 0xAF
_VK_MEDIA_NEXT_TRACK = 0xB0
_VK_MEDIA_PREV_TRACK = 0xB1
_VK_MEDIA_PLAY_PAUSE = 0xB3


def _send_vk(vk_code: int) -> None:
    """Send keydown and keyup for a virtual key code."""
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)  # KEYEVENTF_KEYUP


def system_control(action: str) -> dict[str, Any]:
    """
    Perform common system actions:
    - Volume: 'volume_up', 'volume_down', 'mute', 'unmute'
    - Media: 'play_pause', 'next_track', 'prev_track'
    - Display/Power: 'show_desktop', 'minimize_all', 'lock_screen'
    """
    if not _IS_WINDOWS:
        return {"success": False, "error": "System control requires Windows"}

    act = action.strip().lower()

    try:
        if act in ("mute", "unmute", "toggle_mute"):
            _send_vk(_VK_VOLUME_MUTE)
            return {"success": True, "message": "Toggled volume mute"}

        if act == "volume_up":
            for _ in range(5):
                _send_vk(_VK_VOLUME_UP)
                time.sleep(0.02)
            return {"success": True, "message": "Increased volume"}

        if act == "volume_down":
            for _ in range(5):
                _send_vk(_VK_VOLUME_DOWN)
                time.sleep(0.02)
            return {"success": True, "message": "Decreased volume"}

        if act in ("play_pause", "play", "pause"):
            _send_vk(_VK_MEDIA_PLAY_PAUSE)
            return {"success": True, "message": "Toggled media playback (Play/Pause)"}

        if act == "next_track":
            _send_vk(_VK_MEDIA_NEXT_TRACK)
            return {"success": True, "message": "Skipped to next media track"}

        if act == "prev_track":
            _send_vk(_VK_MEDIA_PREV_TRACK)
            return {"success": True, "message": "Returned to previous media track"}

        if act in ("show_desktop", "minimize_all"):
            # Win+D
            VK_LWIN = 0x5B
            VK_D = 0x44
            ctypes.windll.user32.keybd_event(VK_LWIN, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_D, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(VK_D, 0, 2, 0)
            ctypes.windll.user32.keybd_event(VK_LWIN, 0, 2, 0)
            return {"success": True, "message": "Toggled Show Desktop (minimized/restored all windows)"}

        if act == "lock_screen":
            ctypes.windll.user32.LockWorkStation()
            return {"success": True, "message": "Locked Windows workstation"}

        return {
            "success": False,
            "error": f"Unknown system action '{action}'. Options: volume_up, volume_down, mute, play_pause, next_track, prev_track, show_desktop, lock_screen",
        }
    except Exception as exc:
        return {"success": False, "error": f"System action '{action}' failed: {exc}"}


def open_url(url: str) -> dict[str, Any]:
    """Open any URL in the user's default web browser."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    try:
        opened = webbrowser.open(clean_url)
        if opened:
            return {"success": True, "message": f"Opened {clean_url} in browser", "url": clean_url}
        return {"success": False, "error": f"Failed to launch browser for {clean_url}"}
    except Exception as exc:
        return {"success": False, "error": f"Could not open URL: {exc}"}

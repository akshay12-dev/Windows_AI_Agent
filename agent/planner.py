"""
Task planner: turns a natural-language command into a structured plan of
tool calls. The LLM never executes anything itself — it only produces JSON
describing which registered tools to call, in what order, with what
arguments (per project rule: LLM = brain/planner, Python tools = hands).

Includes fast-path intent matching for instant responses to common direct commands.
"""
from __future__ import annotations

import re
from typing import Any

from agent.llm import LLM
from agent.prompts import build_planner_system
from agent.router import TOOLS
from config import Config
from utils.logger import heartbeat, log_llm, log_plan


class PlanningError(Exception):
    pass


# Phrases meaning "run the last command again"
_RETRY_PATTERNS = [
    re.compile(r"^(try again|retry|redo|do it again|repeat( that)?|same again)\b", re.I),
    re.compile(r"\bprevious (task|command)\b", re.I),
    re.compile(r"\blast (task|command)\b", re.I),
]

_last_command: str | None = None
_session_memory: dict[str, Any] = {
    "last_app": None,
    "last_file": None,
    "last_query": None,
}


def set_last_command(command: str | None) -> None:
    """Restore the last-command memory (used to survive app restarts)."""
    global _last_command
    _last_command = command


def get_session_memory() -> dict[str, Any]:
    return dict(_session_memory)


def update_session_memory(key: str, value: Any) -> None:
    _session_memory[key] = value


def resolve_command(user_command: str) -> str:
    """If user_command is a 'run that again' style phrase, substitute the
    real last command. Otherwise return user_command unchanged."""
    global _last_command
    stripped = user_command.strip()

    if any(p.search(stripped) for p in _RETRY_PATTERNS):
        if _last_command:
            log_llm(f'Interpreting "{stripped}" as: repeat last command -> "{_last_command}"')
            return _last_command
        log_llm("No previous command remembered yet — treating this as a new command.")

    _last_command = stripped
    return stripped


def _match_fast_path(command: str) -> list[dict] | None:
    """
    Direct pattern match for common single-action tasks so they execute
    instantly without incurring a 30-60s local LLM roundtrip.
    """
    cmd = command.strip().lower()

    # System stats / health
    if cmd in ("system stats", "pc stats", "system status", "hardware info", "ram usage", "battery level", "system info", "pc status", "check system"):
        return [{"tool": "get_system_stats", "arguments": {}}]

    # Screenshots
    if cmd in ("screenshot", "take screenshot", "take a screenshot", "capture screen", "screen grab"):
        return [{"tool": "take_screenshot", "arguments": {"save_path": "screenshot.png"}}]

    # Volume & Media controls
    if cmd in ("mute", "unmute", "toggle mute", "mute volume", "mute audio", "silence"):
        return [{"tool": "system_control", "arguments": {"action": "mute"}}]
    if cmd in ("volume up", "increase volume", "louder", "turn up volume"):
        return [{"tool": "system_control", "arguments": {"action": "volume_up"}}]
    if cmd in ("volume down", "decrease volume", "lower volume", "turn down volume", "quieter"):
        return [{"tool": "system_control", "arguments": {"action": "volume_down"}}]
    if cmd in ("play pause", "play/pause", "pause music", "resume music", "play music"):
        return [{"tool": "system_control", "arguments": {"action": "play_pause"}}]
    if cmd in ("next track", "next song", "skip song", "skip track"):
        return [{"tool": "system_control", "arguments": {"action": "next_track"}}]
    if cmd in ("prev track", "previous track", "previous song"):
        return [{"tool": "system_control", "arguments": {"action": "prev_track"}}]

    # Windows desktop & workstation
    if cmd in ("show desktop", "minimize all", "minimize all windows", "hide all windows"):
        return [{"tool": "system_control", "arguments": {"action": "show_desktop"}}]
    if cmd in ("lock pc", "lock screen", "lock workstation", "lock computer"):
        return [{"tool": "system_control", "arguments": {"action": "lock_screen"}}]

    # Clipboard
    if cmd in ("read clipboard", "get clipboard", "show clipboard", "what is on my clipboard", "clipboard content"):
        return [{"tool": "read_clipboard", "arguments": {}}]

    # Open folders
    m_folder = re.match(r"^(?:open|show|view)\s+(downloads|documents|desktop|pictures|music|videos)\s*(?:folder)?$", cmd)
    if m_folder:
        return [{"tool": "open_folder", "arguments": {"folder": m_folder.group(1)}}]

    # Open URLs (e.g. "open https://youtube.com" or "open youtube.com" or "go to google.com")
    m_url = re.match(r"^(?:open|go to|visit)\s+((?:https?://)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)$", cmd)
    if m_url:
        url = m_url.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        return [{"tool": "open_url", "arguments": {"url": url}}]

    # Direct single-word app triggers
    if cmd in ("camera", "webcam", "open camera", "take photo", "start camera", "launch camera"):
        return [{"tool": "open_app", "arguments": {"app": "camera"}}]
    if cmd in ("close camera", "exit camera", "stop camera", "kill camera"):
        return [{"tool": "close_app", "arguments": {"app": "camera"}}]

    if cmd in ("calculator", "calc"):
        return [{"tool": "open_app", "arguments": {"app": "calc"}}]
    if cmd in ("notepad",):
        return [{"tool": "open_app", "arguments": {"app": "notepad"}}]
    if cmd in ("settings", "windows settings"):
        return [{"tool": "open_app", "arguments": {"app": "settings"}}]
    if cmd in ("task manager", "taskmgr"):
        return [{"tool": "open_app", "arguments": {"app": "task manager"}}]

    # Create new folder(s)
    m_mkdir = re.match(
        r"^(?:create|make|add)\s+"
        r"(?:(?P<count>\d+)\s+)?"
        r"(?:new\s+|a\s+|an\s+)?"
        r"(?:folders?|directories|directory)"
        r"(?:\s+(?:named|called)\s+(?P<name>.+?))?"
        r"(?:\s+(?:in|inside|on|at)\s+(?P<where>.+))?$",
        cmd,
    )
    if m_mkdir:
        count = int(m_mkdir.group("count")) if m_mkdir.group("count") else 1
        name = (m_mkdir.group("name") or "").strip()
        where = (m_mkdir.group("where") or "").strip()
        if name:
            # Re-read the name from the original (non-lowercased) command so
            # capitalisation is preserved.
            orig = re.match(
                r"^(?:create|make|add)\s+(?:\d+\s+)?(?:new\s+|a\s+|an\s+)?"
                r"(?:folders?|directories|directory)\s+(?:named|called)\s+(.+)$",
                command.strip(), flags=re.I,
            )
            if orig:
                name = re.split(r"\s+(?:in|inside|on|at)\s+", orig.group(1), maxsplit=1, flags=re.I)[0].strip()
        if where:
            where = re.sub(r"^(?:the|my|a|an)\s+", "", where, flags=re.I)
            if where.lower() in (
                "current folder", "current file", "current directory",
                "this folder", "this directory", "here", "current window",
                "current explorer window", "current location", "this pc",
            ):
                where = ""
            else:
                where = re.sub(r"\s+(?:folder|directory|window)$", "", where, flags=re.I).strip()
        args = {"count": count}
        if name:
            args["name"] = name
        if where:
            args["path"] = where
        return [{"tool": "create_folder", "arguments": args}]

    # Close all File Explorer windows / tabs
    if re.match(
        r"^(?:close|shut)\s+(?:down\s+)?(?:all\s+)?(?:the\s+)?(?:open\s+)?"
        r"(?:file explorer|explorer|folder|folders)(?:\s+(?:windows?|tabs?|folders?))?$",
        cmd,
    ):
        return [{"tool": "close_windows", "arguments": {"match": "File Explorer"}}]

    # Close all (Explorer) tabs
    if re.match(r"^(?:close|shut)\s+(?:all\s+)?(?:the\s+)?(?:open\s+)?tabs?$", cmd):
        return [{"tool": "close_windows", "arguments": {"match": "File Explorer"}}]

    # Close all open files / documents across common editors
    if re.match(
        r"^(?:close|shut)\s+(?:down\s+)?(?:all\s+)?(?:the\s+)?(?:open\s+)?"
        r"(?:files?|documents?)(?:\s+(?:windows?|tabs?))?$",
        cmd,
    ):
        return [
            {"tool": "close_windows", "arguments": {"match": "File Explorer"}},
            {"tool": "close_windows", "arguments": {"process": "notepad.exe"}},
            {"tool": "close_windows", "arguments": {"process": "WINWORD.EXE"}},
            {"tool": "close_windows", "arguments": {"process": "EXCEL.EXE"}},
        ]

    # Generic single-app open (must not contain multi-step keywords like 'and', 'then', 'write', etc.)
    _multi_step_words = {"and", "then", "with", "write", "type", "create", "save", "search", "about"}
    words = set(cmd.split())
    if not (words & _multi_step_words):
        m_app = re.match(r"^(?:open|launch|start|run)\s+(?:the\s+)?([a-zA-Z0-9_\-\.\s]+?)(?:\s+(?:app|application|program|window))?$", cmd)
        if m_app:
            target = m_app.group(1).strip()
            # Normalize filler words: "a new X", "new X", "X tab".
            target = re.sub(r"^(?:a|an|the)\s+", "", target, flags=re.I)
            target = re.sub(r"^(?:a\s+)?new\s+", "", target, flags=re.I).strip()
            target = re.sub(r"\s+(?:tab|window)$", "", target, flags=re.I).strip()
            if not target or target.lower() == "new":
                return None
            # File Explorer goes by many names — but so does Internet Explorer.
            if (
                target.lower() in ("file explorer", "windows explorer", "this pc", "my computer", "computer", "file manager")
                or ("explorer" in target.lower() and "internet" not in target.lower())
            ):
                target = "explorer"
            # If target looks like a website or domain
            if "." in target and not target.endswith((".exe", ".bat", ".cmd")):
                url = target if target.startswith("http") else f"https://{target}"
                return [{"tool": "open_url", "arguments": {"url": url}}]
            if target in ("calculator", "calc.exe"):
                target = "calc"
            return [{"tool": "open_app", "arguments": {"app": target}}]

        # Generic single-app close
        m_close = re.match(r"^(?:close|quit|kill|exit|stop)\s+(?:the\s+)?([a-zA-Z0-9_\-\.\s]+?)(?:\s+(?:app|application|program|window))?$", cmd)
        if m_close:
            target = m_close.group(1).strip()
            # Leave "close all ..." for the LLM (single-app close can't express it).
            if target.lower() == "all" or target.lower().startswith("all "):
                return None
            if target in ("calculator", "calc.exe"):
                target = "calc"
            return [{"tool": "close_app", "arguments": {"app": target}}]

    return None


def plan(user_command: str, llm: LLM | None = None) -> list[dict]:
    llm = llm or LLM()
    user_command = resolve_command(user_command)

    # 1. Fast path check
    if Config.FAST_PATH_ENABLED:
        fast_steps = _match_fast_path(user_command)
        if fast_steps:
            log_plan(f"Fast-path matched {len(fast_steps)} step(s)")
            for i, step in enumerate(fast_steps, start=1):
                arg_preview = ", ".join(f"{k}={v}" for k, v in step["arguments"].items())
                print(f"  {i}. {step['tool']}({arg_preview})")
            return fast_steps

    # 2. LLM Planning path
    log_llm("Understanding command...")
    system = build_planner_system(TOOLS)
    try:
        with heartbeat("Planning"):
            parsed = llm.chat_json(system, user_command)
    except Exception as exc:  # noqa: BLE001
        raise PlanningError(f"Failed to get a valid plan from the LLM: {exc}") from exc

    steps = parsed.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PlanningError("Plan was empty or malformed (expected a non-empty 'steps' list)")

    validated = []
    for step in steps:
        tool = step.get("tool")
        arguments = step.get("arguments", {})
        if tool not in TOOLS:
            raise PlanningError(f"Plan referenced unknown tool '{tool}' — refusing to execute")
        if not isinstance(arguments, dict):
            raise PlanningError(f"Step for '{tool}' has non-dict arguments")
        validated.append({"tool": tool, "arguments": arguments})

    log_plan(f"{len(validated)} step(s) generated")
    for i, step in enumerate(validated, start=1):
        arg_preview = ", ".join(f"{k}={v}" for k, v in step["arguments"].items())
        print(f"  {i}. {step['tool']}({arg_preview})")

    return validated

"""App-level convenience tools that don't fit windows/keyboard/mouse
directly — currently just LLM-driven content generation, used e.g. to write
an essay before typing it into Notepad."""
from __future__ import annotations

from agent.llm import LLM
from agent.prompts import CONTENT_GENERATION_SYSTEM
from utils.logger import heartbeat


def generate_text(topic: str, type: str = "text", llm: LLM | None = None) -> dict:  # noqa: A002
    """Generate prose content (essay, note, email body, etc.) for typing into
    an application. `type` is a free-form hint like 'essay', 'summary'."""
    llm = llm or LLM()
    prompt = f"Write a {type} about: {topic}"
    try:
        with heartbeat(f"Generating {type}"):
            content = llm.chat(CONTENT_GENERATION_SYSTEM, prompt)
        return {"success": True, "content": content.strip()}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"Text generation failed: {exc}"}

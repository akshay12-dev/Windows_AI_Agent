"""Central, env-driven configuration for the agent."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # LLM backend selection
    LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")

    # Ollama
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

    # llama.cpp / LM Studio (OpenAI-compatible /v1/chat/completions servers)
    LLAMACPP_HOST = os.getenv("LLAMACPP_HOST", "http://localhost:8080")
    LMSTUDIO_HOST = os.getenv("LMSTUDIO_HOST", "http://localhost:1234")

    # OpenAI / Compatible Cloud APIs (Groq, OpenRouter, DeepSeek, etc.)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Voice feedback & interactive features
    VOICE_FEEDBACK = _bool("VOICE_FEEDBACK", False)
    FAST_PATH_ENABLED = _bool("FAST_PATH_ENABLED", True)

    # How long to wait for a single LLM call before giving up. Local models
    # on CPU-only hardware can easily need 2-5+ minutes for a single
    # response — raise LLM_TIMEOUT_SECONDS in .env if you keep hitting
    # "Read timed out" errors. Default is generous (10 min) since a timeout
    # mid-task is worse than a slow reply.
    LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "600"))

    # Web search
    WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

    # File search
    FILE_SEARCH_FOLDERS = [
        f.strip()
        for f in os.getenv("FILE_SEARCH_FOLDERS", "Documents,Downloads,Desktop").split(",")
        if f.strip()
    ]
    FILE_SEARCH_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".csv", ".pptx"}

    HOME = Path.home()

    # Persisted state files live next to this module.
    SETTINGS_PATH = Path(__file__).parent / "settings.json"
    HISTORY_PATH = Path(__file__).parent / "command_history.json"

    # User-adjustable settings persisted to settings.json (values loaded from
    # there override the .env / defaults above).
    _SETTING_KEYS = (
        "LLM_BACKEND",
        "OLLAMA_HOST",
        "OLLAMA_MODEL",
        "LLAMACPP_HOST",
        "LMSTUDIO_HOST",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "VOICE_FEEDBACK",
        "FAST_PATH_ENABLED",
        "LLM_TIMEOUT_SECONDS",
    )

    @classmethod
    def file_search_roots(cls):
        roots = []
        for folder in cls.FILE_SEARCH_FOLDERS:
            p = Path(folder)
            roots.append(p if p.is_absolute() else cls.HOME / folder)
        return roots

    @classmethod
    def load_settings(cls) -> None:
        """Apply settings.json on top of the env/default values."""
        try:
            data = json.loads(cls.SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key in cls._SETTING_KEYS:
            if data.get(key) is not None:
                setattr(cls, key, data[key])

    @classmethod
    def save_settings(cls) -> None:
        data = {key: getattr(cls, key) for key in cls._SETTING_KEYS}
        try:
            cls.SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass


Config.load_settings()

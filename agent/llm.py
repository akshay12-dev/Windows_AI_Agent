"""
Local LLM client.

Design goal: the rest of the app only calls `LLM.chat(system, user) -> str`.
Swapping backends (Ollama / llama.cpp / LM Studio, all local) means changing
config, not calling code.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

import requests

from config import Config


class LLMBackend(ABC):
    @abstractmethod
    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        """Return the raw text completion."""


class OllamaBackend(LLMBackend):
    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/")
        self.model = model

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=Config.LLM_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.exceptions.ReadTimeout as exc:
            raise RuntimeError(
                f"Ollama didn't respond within {Config.LLM_TIMEOUT_SECONDS}s. Your model is "
                f"taking longer than that to generate a reply (common on CPU-only hardware "
                f"or with a large model). Raise LLM_TIMEOUT_SECONDS in .env, or switch to a "
                f"smaller/faster OLLAMA_MODEL (e.g. llama3.2:3b, phi3, qwen2.5:3b)."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.host}. Is it running? "
                f"Start it with: ollama serve"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Ollama returned 404 for model '{self.model}' — it isn't pulled "
                    f"locally. Run: ollama pull {self.model}  "
                    f"(or set OLLAMA_MODEL in .env to a model you already have; "
                    f"check with: ollama list)"
                ) from exc
            raise RuntimeError(f"Ollama request failed ({resp.status_code}): {resp.text}") from exc
        data = resp.json()
        return data.get("message", {}).get("content", "")


class OpenAICompatibleBackend(LLMBackend):
    """Works for llama.cpp server, LM Studio, OpenAI, Groq, OpenRouter, etc.,
    which expose an OpenAI-style /v1/chat/completions endpoint."""

    def __init__(self, host: str, model: str = "local-model", api_key: str = ""):
        self.host = host.rstrip("/")
        self.model = model
        self.api_key = api_key

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        endpoint = self.host if self.host.endswith("/chat/completions") else f"{self.host}/v1/chat/completions"
        if "/v1/v1/" in endpoint:
            endpoint = endpoint.replace("/v1/v1/", "/v1/")

        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=Config.LLM_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.exceptions.ReadTimeout as exc:
            raise RuntimeError(
                f"The server didn't respond within {Config.LLM_TIMEOUT_SECONDS}s. "
                f"Raise LLM_TIMEOUT_SECONDS in .env, or use a smaller/faster model."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"Could not reach server at {self.host}. "
                f"Check the server host URL and make sure it is running."
            ) from exc
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(f"Request failed ({resp.status_code}): {resp.text}") from exc
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def ping_backend(backend: str, host: str, model: str = "", api_key: str = "") -> tuple[bool, str]:
    """Test connection to an LLM endpoint and return (success, message)."""
    b = backend.lower().strip()
    try:
        if b == "ollama":
            h = host.rstrip("/")
            r = requests.get(f"{h}/api/tags", timeout=5)
            if r.status_code == 200:
                models = [m.get("name") for m in r.json().get("models", [])]
                model_str = f"Available: {', '.join(models[:4])}" if models else "Connected"
                return True, f"Ollama reachable. {model_str}"
            return False, f"Ollama returned HTTP {r.status_code}"
        else:
            h = host.rstrip("/")
            endpoint = f"{h}/models" if h.endswith("/v1") else f"{h}/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            r = requests.get(endpoint, headers=headers, timeout=5)
            if r.status_code in (200, 401, 403):
                if r.status_code == 200:
                    return True, "Endpoint reachable and responding (HTTP 200)."
                return False, f"Endpoint reached but auth error (HTTP {r.status_code}). Check API key."
            return True, f"Server responded with status {r.status_code}"
    except Exception as exc:
        return False, f"Connection failed: {exc}"


def build_llm() -> LLMBackend:
    backend = Config.LLM_BACKEND.lower()
    if backend == "ollama":
        return OllamaBackend(Config.OLLAMA_HOST, Config.OLLAMA_MODEL)
    if backend == "llamacpp":
        return OpenAICompatibleBackend(Config.LLAMACPP_HOST)
    if backend == "lmstudio":
        return OpenAICompatibleBackend(Config.LMSTUDIO_HOST, model=os.getenv("LMSTUDIO_MODEL", "local-model"))
    if backend in ("openai", "custom", "cloud"):
        return OpenAICompatibleBackend(Config.OPENAI_BASE_URL, model=Config.OPENAI_MODEL, api_key=Config.OPENAI_API_KEY)
    raise ValueError(f"Unknown LLM_BACKEND: {Config.LLM_BACKEND}")


class LLM:
    """Thin facade used everywhere else in the app."""

    def __init__(self):
        self._backend = build_llm()

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        return self._backend.chat(system, user, json_mode=json_mode)

    def chat_json(self, system: str, user: str) -> dict:
        raw = self.chat(system, user, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some local models wrap JSON in markdown fences despite json_mode.
            cleaned = raw.strip().strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            return json.loads(cleaned)

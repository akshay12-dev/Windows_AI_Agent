"""Minimal tagged logger: [LLM] / [PLAN] / [TOOL] / [DONE] / [ERROR]."""
import contextlib
import sys
import threading
import time


def _emit(tag: str, message: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {message}", file=sys.stdout, flush=True)


def log_llm(message: str):
    _emit("LLM", message)


def log_plan(message: str):
    _emit("PLAN", message)


def log_tool(message: str):
    _emit("TOOL", message)


def log_done(message: str):
    _emit("DONE", message)


def log_error(message: str):
    _emit("ERROR", message)


@contextlib.contextmanager
def heartbeat(label: str, interval: float = 8.0):
    """
    Print a periodic '[LLM] <label>... still working (Ns)' line while a slow
    call (typically a local-LLM request) is in flight, so a genuinely slow
    local model doesn't read as a frozen/hung program. Local models running
    on CPU can easily take 30-120+ seconds per call.

    Usage:
        with heartbeat("Generating table"):
            result = llm.chat_json(...)
    """
    stop = threading.Event()
    start = time.time()

    def _tick():
        while not stop.wait(interval):
            elapsed = int(time.time() - start)
            log_llm(f"{label}... still working ({elapsed}s elapsed, this can take a while on a local model)")

    t = threading.Thread(target=_tick, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=0.1)

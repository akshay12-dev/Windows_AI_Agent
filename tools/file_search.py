"""File search tool. Read-only by design — never opens or modifies files
unless a separate, explicit tool call requests that."""
from __future__ import annotations

import os

from config import Config


def search_files(query: str, extensions: list | None = None) -> dict:
    exts = {e.lower() for e in extensions} if extensions else Config.FILE_SEARCH_EXTENSIONS
    query_lower = query.lower()
    results = []

    for root_dir in Config.file_search_roots():
        if not root_dir.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            for fname in filenames:
                name_lower = fname.lower()
                _, ext = os.path.splitext(name_lower)
                if ext not in exts:
                    continue
                # Simple relevance: every query word must appear somewhere
                # in the filename (order-independent).
                if all(word in name_lower for word in query_lower.split()):
                    full_path = os.path.join(dirpath, fname)
                    results.append({"name": fname, "path": full_path, "extension": ext})

    return {"success": True, "results": results}

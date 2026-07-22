"""prompt_toolkit tab-completer for the TerraAI REPL."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

_RESOURCE_RE = re.compile(r'resource\s+"([a-zA-Z0-9_]+)"\s+"([a-zA-Z0-9_]+)"')

SLASH_COMMANDS: list[str] = sorted([
    "/apply", "/apikey", "/arch", "/backend", "/branch", "/branches",
    "/chronicle", "/clear", "/config", "/cost", "/destroy", "/diagram",
    "/diff", "/drift", "/edit", "/exit", "/files", "/help", "/history",
    "/init", "/model", "/models", "/outputs", "/plan", "/providers",
    "/q", "/quit", "/replay", "/resources", "/rollback", "/state",
    "/structure", "/tag", "/tags", "/web", "/workspace", "/workspaces",
])

_CACHE_TTL = 5.0  # seconds between re-reads of workspace files


class TerraAICompleter(Completer):
    """Tab-complete slash commands and Terraform resource addresses.

    Slash commands: matched when the line starts with '/'.
    Resource addresses: matched against the last whitespace-delimited token
    for natural-language prompts that reference an existing resource.
    """

    def __init__(self, workspace_fn: Callable[[], str]) -> None:
        self._workspace_fn = workspace_fn
        self._resource_cache: list[str] = []
        self._cache_ts: float = 0.0

    def invalidate(self) -> None:
        """Force a cache refresh on the next completion call."""
        self._cache_ts = 0.0

    def _workspace(self) -> Path:
        return Path(self._workspace_fn())

    def _resource_addresses(self) -> list[str]:
        now = time.monotonic()
        if now - self._cache_ts < _CACHE_TTL:
            return self._resource_cache

        addresses: set[str] = set()
        ws = self._workspace()

        try:
            for tf in ws.rglob("*.tf"):
                try:
                    text = tf.read_text(encoding="utf-8", errors="ignore")
                    for m in _RESOURCE_RE.finditer(text):
                        addresses.add(f"{m.group(1)}.{m.group(2)}")
                except OSError:
                    pass
        except OSError:
            pass

        state_file = ws / "terraform.tfstate"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                for r in state.get("resources", []):
                    rtype = r.get("type", "")
                    rname = r.get("name", "")
                    if rtype and rname:
                        addresses.add(f"{rtype}.{rname}")
            except Exception:
                pass

        self._resource_cache = sorted(addresses)
        self._cache_ts = now
        return self._resource_cache

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        text = document.text_before_cursor
        stripped = text.lstrip()

        # Slash command completion — only while still typing the command token
        if stripped.startswith("/") and " " not in stripped:
            for cmd in SLASH_COMMANDS:
                if cmd.startswith(stripped):
                    yield Completion(cmd, start_position=-len(stripped))
            return

        # Resource address completion for the last token in natural-language prompts
        tokens = text.split()
        if not tokens:
            return
        word = tokens[-1]
        if len(word) < 3:
            return
        for addr in self._resource_addresses():
            if addr.startswith(word):
                yield Completion(addr, start_position=-len(word))

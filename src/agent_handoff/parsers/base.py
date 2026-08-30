"""Parser contract plus helpers shared by the JSONL family."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path

from agent_handoff.model import Interruption, Message, RawSession, SessionMeta, TodoItem

# Keys whose tool-input values look like file paths.
_PATH_KEYS = ("file_path", "notebook_path", "path", "filepath", "abs_path")

# Command tokens that look like paths but carry zero handoff signal.
_PATH_BLOCKLIST = {"dev/null", "dev/stdout", "dev/stderr", "dev/urandom", "tmp"}
_MIME_PREFIXES = ("application/", "text/", "image/", "audio/", "video/", "multipart/")

# Text that carries no handoff value even though it looks like user content.
# Prefixes without ">" so attribute-bearing variants (<system-reminder
# data-role=…>) are caught too.
_NOISE_MARKERS = (
    "<system-reminder",
    "<local-command",
    "<loaded_context",
    "<project_context",
    "Caveat:",
    "[Request interrupted",
)


class Parser(ABC):
    """A parser turns one CLI's private storage into a RawSession."""

    cli: str

    @abstractmethod
    def list_sessions(self) -> list[SessionMeta]: ...

    @abstractmethod
    def load(self, session_id: str) -> RawSession | None: ...

    def peek_status(self, session_id: str) -> str | None:
        """Lightweight end-state signal, or None when the store has none.

        Only CLIs with a cheap proven signal (e.g. a usage table) implement
        this; callers must treat None as "unknown", never as "clean".
        """
        return None

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def extract_paths(tool_input: dict) -> list[str]:
        """Pull file-ish paths out of a tool call's input dict."""
        found: list[str] = []
        for key in _PATH_KEYS:
            v = tool_input.get(key)
            if isinstance(v, str) and v.strip():
                found.append(v)
        # Bash-style commands: capture absolute-ish path arguments, minus
        # numeric fragments (port/queue IDs) and MIME types from curl -H.
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            for tok in re.findall(r"(?:[\w.\-']+/)+[\w.\-']+", cmd):
                if tok[0].isdigit() or tok.lower() in _PATH_BLOCKLIST:
                    continue
                if any(tok.lower().startswith(m) for m in _MIME_PREFIXES):
                    continue
                found.append(tok)
        return found

    @staticmethod
    def is_noise(text: str) -> bool:
        head = text.lstrip()[:60]
        return any(head.startswith(m) for m in _NOISE_MARKERS)

    @staticmethod
    def clean_text(text: str) -> str:
        """Strip common XML wrapper noise from a turn."""
        text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
        text = re.sub(r"<local-command[^>]*>.*?</local-command[^>]*>", "", text, flags=re.S)
        return text.strip()

    @staticmethod
    def build_raw(
        meta: SessionMeta,
        messages: list[Message],
        todos: list[TodoItem] | None = None,
        files: Counter[str] | None = None,
        tools: Counter[str] | None = None,
        interruption: Interruption | None = None,
    ) -> RawSession:
        return RawSession(
            meta=meta,
            messages=messages,
            todos=todos or [],
            files_touched=files or Counter(),
            tool_counts=tools or Counter(),
            interruption=interruption or Interruption(),
        )


def read_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    """Read a JSONL file defensively; malformed lines are skipped."""
    out: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
            if limit and len(out) >= limit:
                break
    return out


def as_text_blocks(content) -> tuple[str, list[dict]]:
    """Split an assistant/user content payload into (plain_text, tool_blocks)."""
    if isinstance(content, str):
        return content, []
    texts: list[str] = []
    tools: list[dict] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype in ("text", "output_text", "input_text"):
            t = block.get("text") or block.get("content") or ""
            if isinstance(t, str):
                texts.append(t)
        elif btype in ("tool_use", "toolCall", "tool-call", "tool"):
            tools.append(block)
    return "\n".join(t for t in texts if t), tools

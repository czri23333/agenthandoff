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

# Harness text stored in a user turn that no human typed. Matched at the start
# of a turn; used for turn identity (who spoke last), never to delete content.
INJECTED_TURN_PREFIXES = (
    "<task-notification",
    "<environment_context",
    "<codex_internal_context",
    "<conversation_history_summary",
    "<user_instructions",
    "<goal_round",
    "# AGENTS.md instructions",
    "<app-context>",
)

# Pure-environment wrappers, dropped from the text: re-derivable from the machine.
_ENV_WRAPPERS = ("environment_context", "codex_internal_context", "think")

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

    def with_root(self, root: Path) -> Parser:
        """A copy of this parser aimed at another store directory.

        Used by the fixture-backed evidence layer (support matrix, conformance
        checks, tests): every parser already took an optional root in __init__,
        but there was no generic way to say "read this tree instead" — which is
        what makes a support claim reproducible on someone else's clone.
        """
        return type(self)(Path(root))

    def peek_status(self, session_id: str) -> str | None:
        """Lightweight end-state signal, or None when the store has none.

        Only CLIs with a cheap proven signal (e.g. a usage table) implement
        this; callers must treat None as "unknown", never as "clean".
        """
        return None

    def usage(self, session_id: str) -> dict | None:
        """Token/latency accounting for a session, or None if the store
        records none.

        Shape (per-model rows plus totals; missing fields stay None so
        honest absence beats invented zeros):
            {"models": [{"model", "calls", "tokens_in", "tokens_out",
                          "reasoning", "cache_write", "cache_read",
                          "avg_ttft_ms", "tok_per_s"}],
             "totals": {"calls", "tokens_in", "tokens_out"}}
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
        for tag in _ENV_WRAPPERS:
            text = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", text, flags=re.S)
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


def is_injected(text: str) -> bool:
    """True when a turn stored as "user" was emitted by the harness itself.

    Module-level so consumers outside the parser hierarchy (summarize) can use it
    without instantiating a parser.
    """
    head = text.lstrip()[:80]
    return any(head.startswith(m) for m in INJECTED_TURN_PREFIXES)


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

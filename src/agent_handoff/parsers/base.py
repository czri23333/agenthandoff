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


def file_entry(path: Path, raw: bytes, rel: str) -> dict:
    """One verbatim file as a raw-archive entry (see Parser.raw_archive)."""
    import hashlib

    return {
        "path": rel,
        "encoding": "utf-8",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "text": raw.decode("utf-8", "surrogateescape"),
    }


def json_records_entry(path: str, records: list[tuple[str, dict]]) -> dict:
    """One session's record-level archive (SQLite stores) as JSON lines.

    ``records`` is (table, row-dict) pairs; every column of every row is
    kept, including columns no parser reads — verbatim means verbatim.
    """
    import hashlib
    import json as _json

    lines = [
        _json.dumps({"table": table, "row": row}, ensure_ascii=False)
        for table, row in records
    ]
    text = "\n".join(lines)
    return {
        "path": path,
        "encoding": "json",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
    }


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

    def peek_needs_reply(self, session_id: str) -> bool | None:
        """Cheap signal: does the session end on an un-answered user message?

        Mirrors Claude Code Agent View's "Needs input" bucket. Stores without a
        cheap tail probe return None (unknown), never False.
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

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """The session's own storage, byte-faithful, or None when unsupported.

        This is the *verbatim* layer the summarized brief and the parsed
        transcript both sit above: whatever the vendor wrote for this session
        is carried out unchanged — tool calls, system rows, provider metadata,
        unknown future fields — instead of being re-derived by a parser.

        Contract for each entry:
            {"path": str,          # store-relative where possible, else absolute
             "encoding": str,      # "utf-8" (text, exact bytes) | "json" (records)
             "sha256": str,        # of the ORIGINAL bytes / record payload
             "text": str}          # verbatim content

        ``text`` decodes with errors="surrogateescape", so re-encoding with
        ``.encode("utf-8", "surrogateescape")`` restores the original bytes
        exactly; the hash is over those bytes. For SQLite stores there is no
        single file per session, so entries are record-level JSON lines holding
        every column the store wrote (including ones no parser reads).

        Return None only when the store cannot be addressed per session
        (never pretend a copy exists that does not).
        """
        return None

    # -- shared helpers -----------------------------------------------------

    def last_request_tokens(self, session_id: str) -> dict:
        """Token counts of this session's most recent model request, if known.

        Context pressure belongs to a single request. The session total keeps
        growing across compactions and retries, so `total / window` would claim a
        400-call session sits at 4000% of its window. A store that cannot report
        the per-request figure leaves this empty, and `watch` says "unknown"
        rather than inventing a number.
        """
        return {}

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
        # The product timeline shows data-role="user-context" reminders as
        # regular user turns (only compact-summary gets special handling
        # there); dropping the whole turn hides real conversation. Compact
        # summaries stay noise — they duplicate history the transcript keeps.
        if head.startswith("<system-reminder"):
            return 'data-role="user-context"' not in text.lstrip()[:120]
        return any(head.startswith(m) for m in _NOISE_MARKERS)

    @staticmethod
    def clean_text(text: str) -> str:
        """Strip common XML wrapper noise from a turn."""
        text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
        text = re.sub(r"<local-command[^>]*>.*?</local-command[^>]*>", "", text, flags=re.S)
        for tag in _ENV_WRAPPERS:
            text = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", text, flags=re.S)
        return text.strip()

    def msg(self, role: str, raw: str, **kw) -> Message:
        """Build a turn keeping the verbatim source beside the cleaned text.

        ``raw`` is the turn exactly as the store holds it; ``text`` (in kw)
        is the cleaned display form. When cleaning changed nothing, raw_text
        stays None — text IS verbatim. Callers that synthesize prefixes
        ([思考]/[工具]) pass the assembled string as both.
        """
        text = kw.get("text", "")
        kw["raw_text"] = raw if raw != text else None
        m = Message(role=role, **kw)
        # Honest gauge: length-based estimate when the store records nothing.
        # CJK chars carry ~1 token each; latin ~4 chars per token. Displayed
        # with ≈, never aggregated as vendor truth.
        if (
            m.tokens_in is None
            and m.tokens_out is None
            and m.tokens_estimated is None
            and text.strip()
        ):
            cjk = sum(
                1
                for ch in text
                if "\u4e00" <= ch <= "\u9fff"
                or "\u3400" <= ch <= "\u4dbf"
                or "\uf900" <= ch <= "\ufaff"
            )
            latin = max(0, len(text) - cjk)
            m.tokens_estimated = cjk + max(1, latin // 4) if text.strip() else None
        return m

    @staticmethod
    def apply_cloud_overlay(messages: list, session_id: str) -> int:
        """Attribute user-exported cloud billing to turns by timestamp.

        Reads ``~/.agenthandoff/cloud-usage/<sid>.json`` (see
        ``_cloud_overlay`` contract in jsonl_family); each cloud turn fills
        model/tokens of the nearest unattributed assistant message within
        ±2s. Returns the number of attributed messages. Absent file = 0,
        zero impact.
        """
        try:
            import json as _json
            from datetime import datetime as _dt

            from agent_handoff.locations import home as _home
        except ImportError:
            return 0
        try:
            path = _home() / ".agenthandoff" / "cloud-usage" / f"{session_id}.json"
            if not path.is_file():
                return 0
            data = _json.loads(path.read_text(encoding="utf-8", errors="replace"))
            turns = data.get("turns") if isinstance(data, dict) else None
            if not isinstance(turns, list):
                return 0
        except (OSError, ValueError):
            return 0
        hit = 0
        for t in turns:
            if not isinstance(t, dict):
                continue
            try:
                tat = _dt.fromisoformat(str(t.get("at") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            best = None
            best_d = 2.0
            for m in messages:
                if m.role != "assistant" or not m.at:
                    continue
                if m.tokens_in is not None or m.tokens_out is not None:
                    continue
                try:
                    mat = _dt.fromisoformat(str(m.at).replace("Z", "+00:00"))
                except ValueError:
                    continue
                d = abs((mat - tat).total_seconds())
                if d < best_d:
                    best, best_d = m, d
            if best is None:
                continue
            if t.get("model"):
                best.model = best.model or str(t["model"])
            for k, f in (("tokens_in", "tokens_in"), ("tokens_out", "tokens_out"),
                         ("reasoning", "tokens_reasoning")):
                v = t.get(k)
                if isinstance(v, int) and getattr(best, f) is None:
                    setattr(best, f, v)
            hit += 1
        return hit

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
    """Split an assistant/user content payload into (plain_text, tool_blocks).

    `thinking` blocks (IDE task transcripts) fold into the text with a
    [思考] prefix — the product timeline shows them, dropping them loses
    turns. Same convention as the jsonl_family reasoning rows.
    """
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
        elif btype == "thinking":
            t = block.get("thinking") or block.get("text") or block.get("content") or ""
            if isinstance(t, str) and t.strip():
                texts.append(f"[思考] {t}")
        elif btype in ("tool_use", "toolCall", "tool-call", "tool"):
            tools.append(block)
    return "\n".join(t for t in texts if t), tools

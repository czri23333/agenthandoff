"""Core data model shared by every parser and renderer.

The pipeline is: parser -> RawSession -> summarize -> HandoffBundle -> render.
Parsers only need to produce a RawSession; everything downstream is provider
agnostic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone


def ts_to_iso(value: float | int | str | None) -> str | None:
    """Normalize epoch milliseconds/seconds or an ISO string to ISO-8601 UTC.

    Numeric values below 1e12 are treated as seconds, anything larger as
    milliseconds. Strings are parsed as ISO-8601. Returns None for
    missing/zero/unparseable input so callers can omit the field.
    """
    if not value:
        return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    v = float(value)
    if v > 1e12:
        v /= 1000.0
    if v <= 0:
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc).isoformat(timespec="seconds")


@dataclass
class SessionMeta:
    """Identity and provenance of the captured session."""

    cli: str
    session_id: str
    title: str
    cwd: str = ""
    started_at: str | None = None
    updated_at: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    source_path: str = ""


@dataclass
class Message:
    """A single conversation turn (tool noise already stripped by the parser)."""

    role: str  # "user" | "assistant"
    text: str
    at: str | None = None


@dataclass
class TodoItem:
    content: str
    status: str = "pending"  # pending | in_progress | completed
    priority: str = ""


@dataclass
class RawSession:
    """Provider-neutral extraction of one session."""

    meta: SessionMeta
    messages: list[Message] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    files_touched: Counter[str] = field(default_factory=Counter)
    tool_counts: Counter[str] = field(default_factory=Counter)

    @property
    def user_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role == "user"]

    @property
    def assistant_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role == "assistant"]

    def last_message(self, role: str) -> Message | None:
        candidates = [m for m in self.messages if m.role == role and m.text.strip()]
        return candidates[-1] if candidates else None


@dataclass
class HandoffBundle:
    """The structured handoff state rendered into the bundle format."""

    meta: SessionMeta
    objective: str = ""
    done: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    directives: list[str] = field(default_factory=list)  # key user corrections/asks
    files: list[tuple[str, int]] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    context_notes: list[str] = field(default_factory=list)  # last assistant conclusions
    tool_summary: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bundle_version": "0.1",
            "meta": {
                "cli": self.meta.cli,
                "session_id": self.meta.session_id,
                "title": self.meta.title,
                "cwd": self.meta.cwd,
                "started_at": self.meta.started_at,
                "updated_at": self.meta.updated_at,
                "model": self.meta.model,
                "tokens_in": self.meta.tokens_in,
                "tokens_out": self.meta.tokens_out,
                "source_path": self.meta.source_path,
            },
            "objective": self.objective,
            "state": {
                "done": self.done,
                "in_progress": self.in_progress,
                "blocked": self.blocked,
            },
            "directives": self.directives,
            "files_touched": [{"path": p, "hits": n} for p, n in self.files],
            "next_steps": self.next_steps,
            "context_notes": self.context_notes,
            "tool_summary": [{"tool": t, "calls": n} for t, n in self.tool_summary],
        }

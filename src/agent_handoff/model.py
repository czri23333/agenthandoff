"""Core data model shared by every parser and renderer.

The pipeline is: parser -> RawSession -> summarize -> HandoffBundle -> render.
Parsers only need to produce a RawSession; everything downstream is provider
agnostic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone


def ts_to_iso(value: float | int | str | datetime | None) -> str | None:
    """Normalize epoch ms/seconds, an ISO string, or a datetime to ISO-8601 UTC.

    Numeric values below 1e12 are treated as seconds, anything larger as
    milliseconds. Returns None for missing/zero/unparseable input so callers
    can omit the field.
    """
    if value is None or value == 0 or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
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
    """Identity and provenance of the captured session.

    ``provider`` is the model route behind the session when the store
    exposes one (e.g. ``builtin:bigmodel-start-plan``) — the thing that runs
    out of quota. ``origin`` distinguishes harness variants of the same CLI
    (desktop vs CLI vs IDE). ``parent_session_id`` links subagent/child
    sessions to their spawner. ``account`` is intentionally *not* scraped
    from stores: multi-account setups differ per CLI and credentials are
    none of our business — the user annotates it via ``capture --note``.
    """

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
    provider: str | None = None
    origin: str | None = None
    parent_session_id: str | None = None
    # Assistant identity as the product shows it (workbuddy
    # assistant-display snapshots: expert name + avatar URL). Display-only;
    # never a credential, URLs point at the vendor's public CDN.
    expert_name: str | None = None
    expert_avatar: str | None = None
    notes: list[str] = field(default_factory=list)
    # Task kind as the store reports it (zcode: interactive | subagent_child …).
    # Drives grouping: the app itself separates child runs from conversations.
    task_type: str | None = None
    # How the title was produced (zcode: generated | first_input …). A
    # first_input title is the user's own words; generated is the model's.
    title_source: str | None = None
    # Permission mode the session ran under (zcode: {"mode":"yolo"|"plan"…}).
    permission: str | None = None
    # Files the user attached to the conversation (zcode file parts:
    # filename + path). Distinct from files a tool touched mid-run.
    attachments: list[str] = field(default_factory=list)


@dataclass
class Message:
    """A single conversation turn (tool noise already stripped by the parser).

    The optional billing fields carry what the store records per turn: which
    model answered and how many tokens that request consumed. Parsers fill
    them when the dialect has them; None means "the store says nothing".
    """

    role: str  # "user" | "assistant"
    text: str
    at: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_reasoning: int | None = None
    # Deterministic length-based estimate (~4 chars/token, CJK-aware) used
    # ONLY when the store records no billing. Displayed with a ≈ prefix and
    # never mixed into usage() aggregates — an honest gauge, not vendor truth.
    tokens_estimated: int | None = None
    # Set when the turn came from a sub-agent transcript (label = which one);
    # None for the main conversation. Lets the UI nest sub-agent work under the
    # parent session instead of interleaving it flat.
    subagent: str | None = None
    # Measured cost of this turn in the vendor's own billing unit, keyed by
    # the request id the store records (workbuddy session_usage.credit_json:
    # conversationRequestId -> credits). Per-request attribution, never split.
    credits: float | None = None
    # Measured elapsed ms for this turn from the store's own clocks (e.g.
    # CherryStudio metrics.time_completion_millsec). A verifiable cost proxy
    # where token billing is absent. Server fills it from timestamps when the
    # store records none.
    dur_ms: int | None = None
    # The turn exactly as the store holds it, before clean_text/is_noise
    # trimming. None means the parser kept everything (nothing was trimmed)
    # or the dialect has no trimmable wrappers — either way text IS verbatim.
    # Lets the cockpit offer a 原文 view without re-reading the store.
    raw_text: str | None = None


@dataclass
class TodoItem:
    content: str
    status: str = "pending"  # pending | in_progress | completed
    priority: str = ""


@dataclass
class Interruption:
    """Evidence about how the session actually ended.

    Sessions rarely end cleanly — quota exhaustion, context-window death,
    user Ctrl+C, model errors and max-token truncation all leave the next
    session with a misleading picture unless surfaced explicitly. Parsers
    fill what their store can prove; summarize adds cross-CLI inference
    (e.g. a dangling user message with no reply).
    """

    kind: str = "clean"
    # clean | user_pending | cancelled | context_exceeded | length_truncated
    # | error | unknown
    detail: str = ""
    pending_user_text: str = ""  # set when kind == user_pending

    @property
    def detected(self) -> bool:
        return self.kind != "clean"

    def describe(self) -> str:
        labels = {
            "user_pending": "session ended with an un-answered user message",
            "cancelled": "cancelled by user",
            "context_exceeded": "context window exceeded",
            "length_truncated": "last assistant reply cut off by token limit",
            "error": "model error",
            "unknown": "abrupt end (no clean-finish evidence)",
        }
        base = labels.get(self.kind, self.kind)
        return f"{base}: {self.detail}" if self.detail else base


@dataclass
class CompactionEvent:
    """A context-window compaction inside a session.

    Long sessions are compacted many times; after each compaction the early
    messages exist only as a model-written summary. A transcript that hides
    this is lying about its own completeness — the marker must be visible.
    """

    at: str | None = None
    reason: str = ""  # e.g. context_limit
    pre_tokens: int | None = None
    post_tokens: int | None = None
    auto: bool = True


@dataclass
class RawSession:
    """Provider-neutral extraction of one session."""

    meta: SessionMeta
    messages: list[Message] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    files_touched: Counter[str] = field(default_factory=Counter)
    tool_counts: Counter[str] = field(default_factory=Counter)
    interruption: Interruption = field(default_factory=Interruption)
    compactions: list[CompactionEvent] = field(default_factory=list)

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
    interruption: Interruption = field(default_factory=Interruption)
    topics: list[tuple[str, int]] = field(default_factory=list)  # (segment opener, msg count)
    # Verbatim tail, oldest first: (role, text). The brief's most protected
    # content, because it is what a context death takes with it.
    recent: list[tuple[str, str]] = field(default_factory=list)
    # Full verbatim dialogue (oldest first) for lossless handoff. Populated only
    # when capture uses --full; empty for the default lossy bundle.
    full_transcript: list[tuple[str, str]] = field(default_factory=list)
    # Byte-faithful original storage (see Parser.raw_archive): the vendor's
    # own lines — tool calls, system rows, unknown fields — carried unchanged.
    # Populated only when capture uses --full --raw.
    raw_files: list[dict] = field(default_factory=list)
    # The tail of the last assistant turn when it was cut off mid-sentence, so
    # the successor continues the sentence instead of inventing a new one.
    unfinished: str = ""

    def to_dict(self) -> dict:
        return {
            "bundle_version": "0.2",
            "interruption": {
                "kind": self.interruption.kind,
                "detail": self.interruption.detail,
                "pending_user_text": self.interruption.pending_user_text,
            },
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
                "provider": self.meta.provider,
                "origin": self.meta.origin,
                "parent_session_id": self.meta.parent_session_id,
                "expert_name": self.meta.expert_name,
                "expert_avatar": self.meta.expert_avatar,
                "notes": self.meta.notes,
                "task_type": self.meta.task_type,
                "title_source": self.meta.title_source,
                "permission": self.meta.permission,
                "attachments": list(self.meta.attachments),
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
            "topics": [{"opener": o, "messages": n} for o, n in self.topics],
            "recent": [{"role": r, "text": t} for r, t in self.recent],
            "full_transcript": [{"role": r, "text": t} for r, t in self.full_transcript],
            "raw_files": list(self.raw_files),
            "unfinished": self.unfinished,
        }

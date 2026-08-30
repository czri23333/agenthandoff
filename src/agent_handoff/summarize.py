"""Turn a RawSession into a structured HandoffBundle using deterministic heuristics.

No LLM, no API keys, no network: every field is reproducible from the raw
session. The heuristics favor signal-dense content — user corrections, todo
state, and the final assistant conclusion — over a naive transcript dump.
Interruption awareness: sessions that ended mid-flight (quota exhausted,
cancelled, truncated) are detected and surfaced instead of silently
presenting a half-finished state as if it were a conclusion.
"""

from __future__ import annotations

import re
from datetime import datetime

from agent_handoff.model import HandoffBundle, Interruption, Message, RawSession

# Sentences in user turns that tend to carry durable direction/corrections.
_DIRECTIVE_CUES = re.compile(
    r"(不要|不行|不对|错了|应该是|改用|换成|记住|必须|别再|直接用|要求|注意|问题在|根因|"
    r"don't|do not|instead|should be|must|wrong|remember|use .*? not|fix it|no,)",
    re.IGNORECASE,
)

_MAX_ITEM = 220  # per-list-item char budget
_MAX_NOTE = 600

# A note that doesn't end like a finished statement is treated as a cut-off
# fragment and dropped rather than presented as a conclusion.
_ENDING_PUNCT = tuple("。．.!?！？…」』】）)]}\"'”’")


def _looks_truncated(text: str) -> bool:
    return bool(text) and not text.rstrip().endswith(_ENDING_PUNCT)


def _clip(text: str, limit: int = _MAX_ITEM) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _pick_directives(raw: RawSession, limit: int = 8) -> list[str]:
    """User turns that look like durable direction, deduplicated."""
    seen: set[str] = set()
    out: list[str] = []
    for m in raw.user_messages:
        for sentence in re.split(r"(?<=[。.!?！？\n])", m.text):
            s = sentence.strip()
            if len(s) < 4 or len(s) > 200:
                continue
            if _DIRECTIVE_CUES.search(s) and s not in seen:
                seen.add(s)
                out.append(_clip(s))
                if len(out) >= limit:
                    return out
    return out


def _split_todo_state(raw: RawSession) -> tuple[list[str], list[str], list[str]]:
    """Group todos by the last recorded status of each content string."""
    state: dict[str, str] = {}
    order: list[str] = []
    for t in raw.todos:
        if t.content not in order:
            order.append(t.content)
        state[t.content] = t.status
    done = [_clip(c) for c in order if state.get(c) == "completed"]
    doing = [_clip(c) for c in order if state.get(c) == "in_progress"]
    blocked = [_clip(c) for c in order if state.get(c) not in ("completed", "in_progress")]
    return done, doing, blocked


def summarize(raw: RawSession, max_notes: int = 3) -> HandoffBundle:
    bundle = HandoffBundle(meta=raw.meta)

    # The CLI-generated session title summarizes intent better than the first
    # user message (which may be a bare "你好"); fall back when title is just
    # an id.
    title = (raw.meta.title or "").strip()
    if title and title != raw.meta.session_id:
        bundle.objective = _clip(title, 300)
    else:
        first_user = raw.user_messages[0] if raw.user_messages else None
        bundle.objective = _clip(first_user.text, 300) if first_user else raw.meta.title

    bundle.topics = _topic_segments(raw)
    if bundle.topics:
        bundle.objective += f" (multi-topic session: {len(bundle.topics)} segments)"

    done, doing, blocked = _split_todo_state(raw)
    bundle.done, bundle.in_progress, bundle.blocked = done, doing, blocked

    if not raw.todos:
        # Without todo data, fall back to "what was asked" -> next_steps.
        bundle.next_steps = [
            _clip(m.text, 160) for m in raw.user_messages[-3:] if not _DIRECTIVE_CUES.search(m.text)
        ] or ["Review the captured transcript and define next steps."]

    bundle.directives = _pick_directives(raw)

    bundle.files = [
        (p, n) for p, n in raw.files_touched.most_common(15) if len(p) < 240
    ]
    bundle.tool_summary = raw.tool_counts.most_common(8)

    # Last assistant messages are the freshest self-reported state.
    for m in reversed(raw.assistant_messages):
        note = _clip(m.text, _MAX_NOTE)
        if len(note) > 20:
            if _looks_truncated(note):
                if bundle.interruption.kind == "clean":
                    bundle.interruption = Interruption(
                        kind="unknown",
                        detail="last assistant message does not end like a finished statement",
                    )
                continue  # a cut-off fragment must not pose as a conclusion
            bundle.context_notes.append(note)
        if len(bundle.context_notes) >= max_notes:
            break
    bundle.context_notes.reverse()

    if not bundle.next_steps and not bundle.in_progress:
        bundle.next_steps = ["Continue from the last assistant summary in context_notes."]

    _finalize_interruption(raw, bundle)
    return bundle


def _topic_segments(raw: RawSession, gap_hours: float = 6.0) -> list[tuple[str, int]]:
    """Split a session into topic segments by gaps between user messages.

    A long silence followed by a new user request usually means the session
    drifted onto different work (the "mixed session"). Segments are reported
    so bundles don't smuggle unrelated context into the next session.
    """
    users = raw.user_messages
    if len(users) < 2:
        return []
    segments: list[list[Message]] = [[users[0]]]
    for prev, cur in zip(users, users[1:], strict=False):
        t_prev = _parse_iso(prev.at)
        t_cur = _parse_iso(cur.at)
        if t_prev and t_cur and (t_cur - t_prev).total_seconds() >= gap_hours * 3600:
            segments.append([])
        segments[-1].append(cur)
    if len(segments) < 2:
        return []
    out: list[tuple[str, int]] = []
    for seg in segments:
        opener = _clip(seg[0].text, 120)
        out.append((opener, len(seg)))
    return out


def _parse_iso(iso: str | None):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _finalize_interruption(raw: RawSession, bundle: HandoffBundle) -> None:
    """Cross-CLI inference on top of parser-provided evidence.

    The strongest universal signal: the newest non-empty message is the
    user's, i.e. an instruction was issued and never answered. That pending
    instruction becomes next step #1 — quitting mid-turn is the normal case
    for quota-dead sessions, and the successor must know it is the thing to
    resume.
    """
    if raw.interruption.detected:
        bundle.interruption = raw.interruption
        if bundle.interruption.kind == "length_truncated" and bundle.context_notes:
            bundle.context_notes.pop(0)  # the truncated reply masquerading as oldest note
    elif raw.user_messages and raw.assistant_messages:
        last_user_at = raw.user_messages[-1].at or ""
        last_asst_at = raw.assistant_messages[-1].at or ""
        if last_user_at >= last_asst_at:
            pending = _clip(raw.user_messages[-1].text, 300)
            if not _looks_truncated(pending) or len(pending) > 4:
                bundle.interruption = Interruption(
                    kind="user_pending",
                    detail="newest message is an un-answered user instruction",
                    pending_user_text=pending,
                )
                bundle.next_steps.insert(0, f"[pending from interrupted session] {pending}")

"""Turn a RawSession into a structured HandoffBundle using deterministic heuristics.

No LLM, no API keys, no network: every field is reproducible from the raw
session. The heuristics favor signal-dense content — user corrections, todo
state, and the final assistant conclusion — over a naive transcript dump.
"""

from __future__ import annotations

import re

from agent_handoff.model import HandoffBundle, RawSession

# Sentences in user turns that tend to carry durable direction/corrections.
_DIRECTIVE_CUES = re.compile(
    r"(不要|不行|不对|错了|应该是|改用|换成|记住|必须|别再|直接用|要求|注意|问题在|根因|"
    r"don't|do not|instead|should be|must|wrong|remember|use .*? not|fix it|no,)",
    re.IGNORECASE,
)

_MAX_ITEM = 220  # per-list-item char budget
_MAX_NOTE = 600


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
            bundle.context_notes.append(note)
        if len(bundle.context_notes) >= max_notes:
            break
    bundle.context_notes.reverse()

    if not bundle.next_steps and not bundle.in_progress:
        bundle.next_steps = ["Continue from the last assistant summary in context_notes."]
    return bundle

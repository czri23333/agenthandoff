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
from agent_handoff.parsers.base import is_injected

# Sentences in user turns that tend to carry durable direction/corrections.
_DIRECTIVE_CUES = re.compile(
    r"(不要|不行|不对|错了|应该是|改用|换成|记住|必须|别再|直接用|要求|注意|问题在|根因|"
    r"don't|do not|instead|should be|must|wrong|remember|use .*? not|fix it|no,)",
    re.IGNORECASE,
)

_MAX_ITEM = 220  # per-list-item char budget
_MAX_NOTE = 600

# Verbatim-tail budgets. A session that died mid-flight gets a deeper tail:
# that is precisely the case where the successor has the least to work with.
_RECENT_BUDGET = 6000
_RECENT_BUDGET_DEAD = 10000
# Turns kept no matter what the budget says (OpenCode protects the last 2 user
# turns for the same reason).
_RECENT_MIN_TURNS = 6
_UNFINISHED_CHARS = 1200

# A note that doesn't end like a finished statement is treated as a cut-off
# fragment and dropped rather than presented as a conclusion.
_ENDING_PUNCT = tuple("。．.!?！？…」』】）)]}\"'”’")


def _looks_truncated(text: str) -> bool:
    return bool(text) and not text.rstrip().endswith(_ENDING_PUNCT)


# Markdown structure that must never reach a bundle line: link targets (paths
# and URLs, which are already captured as file anchors) and code ticks.
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_MD_CODE = re.compile(r"`+")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")

# Pairs whose imbalance means a fragment was cut mid-token.
_PAIRS = (("(", ")"), ("[", "]"), ("“", "”"), ("「", "」"), ("『", "』"))


def _collapse_markdown(text: str) -> str:
    """Flatten markup that is structure, not content.

    ``[label](target.md)`` becomes ``label``. Splitting a sentence at the "."
    inside a link target is what produced the shipped garbage directive
    ``md) — 用户跑的是 …``; the target itself carries no instruction, so keeping
    the label and dropping the target is both safe and shorter.
    """
    text = _MD_IMAGE.sub(lambda m: m.group(1), text)
    text = _MD_LINK.sub(lambda m: m.group(1) or m.group(2), text)
    return _MD_CODE.sub("", text)


def _balanced(text: str) -> bool:
    """True when the fragment closes everything it opens.

    A last-resort guard: if a future splitter ever cuts inside markup again,
    an unbalanced fragment is dropped instead of being published as a directive.
    """
    for open_ch, close_ch in _PAIRS:
        if text.count(open_ch) != text.count(close_ch):
            return False
    return text.count('"') % 2 == 0


def _sentences(text: str) -> list[str]:
    """Candidate statements from one message, split after markup is flattened.

    Newlines separate list items and paragraphs, so they end a sentence here —
    but only after ``_collapse_markdown`` removed the link targets whose dots
    used to fool the split.
    """
    cleaned = _collapse_markdown(text)
    parts = re.split(r"(?<=[。．!！?？])|(?<=\.)\s+|\n+", cleaned)
    return [p.strip() for p in parts if p and p.strip()]


def _clip(text: str, limit: int = _MAX_ITEM) -> str:
    text = re.sub(r"\s+", " ", _collapse_markdown(text)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _pick_directives(messages: list[Message], limit: int = 8) -> list[str]:
    """User turns that look like durable direction, deduplicated.

    Lines quoted back from compaction summaries ("- …" / “…” bullet echoes)
    are skipped: they are a summary's paraphrase, not the user speaking.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in messages:
        for s in _sentences(m.text):
            if len(s) < 4 or len(s) > 200:
                continue
            if s.startswith(("-", "—", "•", '"', "“", "「")):
                continue
            if not _balanced(s):
                continue
            if _DIRECTIVE_CUES.search(s) and s not in seen:
                seen.add(s)
                out.append(_clip(s))
                if len(out) >= limit:
                    return out
    return out


def _last_segment_start(raw: RawSession, gap_hours: float = 6.0) -> str:
    """Timestamp of the first user message in the active (last) topic segment.

    Directives from earlier segments belong to finished topics and would
    mislead a successor who is taking over the *current* thread.
    """
    users = raw.user_messages
    if not users:
        return ""
    start = users[0].at or ""
    for prev, cur in zip(users, users[1:], strict=False):
        t_prev = _parse_iso(prev.at)
        t_cur = _parse_iso(cur.at)
        if t_prev and t_cur and (t_cur - t_prev).total_seconds() >= gap_hours * 3600:
            start = cur.at or start
    return start


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

    # With todos: unfinished items ARE the next steps. Without: fall back to
    # the last user asks. (Previously next_steps stayed empty whenever todos
    # existed — a dead path that produced "(none recorded)" briefs.)
    bundle.next_steps = doing + blocked
    if not raw.todos:
        bundle.next_steps = [
            _clip(m.text, 160) for m in raw.user_messages[-3:] if not _DIRECTIVE_CUES.search(m.text)
        ] or ["Review the captured transcript and define next steps."]

    # Directives from a *previous topic segment* mislead the successor — they
    # belong to finished topics, not the thread being handed over. Mixed
    # sessions take directives from the active (last) segment only.
    if bundle.topics:
        last_start = _last_segment_start(raw)
        scope = [m for m in raw.user_messages if (m.at or "") >= last_start]
    else:
        scope = raw.user_messages
    bundle.directives = _pick_directives(scope)

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

    # After finalisation: the end-state must be settled before we decide how
    # deep the verbatim tail needs to be.
    dead = bundle.interruption.kind not in ("clean", "")
    bundle.recent = _pick_recent(raw, _RECENT_BUDGET_DEAD if dead else _RECENT_BUDGET)
    bundle.unfinished = _unfinished(raw, bundle)
    return bundle


def _pick_recent(raw: RawSession, budget: int) -> list[tuple[str, str]]:
    """Verbatim tail of the dialogue, oldest first.

    Trimmed from the *oldest* end: the newest turns are where the work lives, and
    a handoff that loses them forces the successor to rediscover state that was
    already established. An oversized final turn keeps its **end**, because that is
    where the sentence broke off.
    """
    turns = [(m.role, m.text.strip()) for m in raw.messages if m.text and m.text.strip()]
    keep: list[tuple[str, str]] = []
    used = 0
    for index, (role, text) in enumerate(reversed(turns)):
        forced = index < _RECENT_MIN_TURNS
        if used + len(text) > budget and not forced:
            break
        if len(text) > budget:
            text = "\u2026" + text[-(budget // 2) :]
        keep.append((role, text))
        used += len(text)
    keep.reverse()
    return keep


def _unfinished(raw: RawSession, bundle: HandoffBundle) -> str:
    """The cut-off tail of the last assistant turn, when there is one."""
    dead_kinds = ("length_truncated", "context_exceeded", "user_pending", "unknown")
    if bundle.interruption.kind not in dead_kinds:
        return ""
    last = raw.last_message("assistant")
    if last is None:
        return ""
    text = last.text.strip()
    if bundle.interruption.kind != "length_truncated" and not _looks_truncated(text):
        return ""
    return text[-_UNFINISHED_CHARS:]


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


def last_human_user(raw: RawSession) -> Message | None:
    """The newest user turn a human actually typed.

    Harnesses inject their own "user" messages (sub-agent notifications,
    environment dumps, AGENTS.md preludes). Counting those as human instructions
    produced false "the user asked and nobody answered" verdicts. See
    docs/context-management-survey.md for what each vendor injects.
    """
    for message in reversed(raw.user_messages):
        if not message.text or not message.text.strip():
            continue
        if is_injected(message.text):
            continue
        return message
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
    else:
        human = last_human_user(raw)
        if human is not None and raw.assistant_messages:
            last_user_at = human.at or ""
            last_asst_at = raw.assistant_messages[-1].at or ""
            if last_user_at >= last_asst_at:
                pending = _clip(human.text, 300)
                if not _looks_truncated(pending) or len(pending) > 4:
                    bundle.interruption = Interruption(
                        kind="user_pending",
                        detail="newest message is an un-answered user instruction",
                        pending_user_text=pending,
                    )
                    bundle.next_steps.insert(
                        0, f"[pending from interrupted session] {pending}"
                    )

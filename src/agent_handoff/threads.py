"""Task-thread clustering: which sessions across CLIs are actually one job.

Users rarely do one thing per session: a task thread ("fix the H3 pipeline")
spans multiple sessions, often across several CLIs, while a single session
may mix several unrelated topics. Both directions matter for handoff:

* grouping sibling sessions so the successor sees the whole thread;
* spotting multi-topic sessions so a bundle does not smuggle in unrelated
  context.

Deterministic signals only (no embeddings, no LLM):

1. parent lineage — child sessions inherit their parent's thread;
2. file overlap — Jaccard similarity of normalized touched-file sets;
3. shared title tokens — English words and Chinese character bigrams;
4. time window — signals only connect sessions that could plausibly be
   the same work effort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from agent_handoff.model import SessionMeta

DEFAULT_WINDOW_DAYS = 21
DEFAULT_MIN_JACCARD = 0.15

_STOP_TOKENS = {"the", "a", "an", "of", "for", "and", "to", "in", "on", "with"}


def _parse_ts(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_path(p: str) -> str:
    """Lowercase, forward-slash path so parsers' differing styles can overlap."""
    return p.replace("\\\\", "/").replace("\\", "/").strip().lower()


def title_tokens(title: str) -> set[str]:
    """English/number words + Chinese character bigrams from a session title."""
    tokens: set[str] = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", title):
        tokens.add(w.lower())
    han = re.findall(r"[\u4e00-\u9fff]", title)
    tokens.update(a + b for a, b in zip(han, han[1:], strict=False))
    return tokens - {t for t in tokens if t in _STOP_TOKENS}


@dataclass
class SessionNode:
    meta: SessionMeta
    files: set[str] = field(default_factory=set)
    tokens: set[str] = field(default_factory=set)


@dataclass
class Thread:
    sessions: list[SessionNode] = field(default_factory=list)

    @property
    def last_active(self) -> str | None:
        return max(
            (s.meta.updated_at or s.meta.started_at or "" for s in self.sessions),
            default=None,
        ) or None

    @property
    def clis(self) -> list[str]:
        return sorted({s.meta.cli for s in self.sessions})


def _within_window(a: SessionNode, b: SessionNode, window_days: int) -> bool:
    ta = _parse_ts(a.meta.updated_at or a.meta.started_at)
    tb = _parse_ts(b.meta.updated_at or b.meta.started_at)
    if ta is None or tb is None:
        return True  # missing timestamps must not silently disconnect sessions
    return abs((ta - tb).total_seconds()) <= window_days * 86400


def _similar(a: SessionNode, b: SessionNode, min_jaccard: float) -> bool:
    if a.meta.parent_session_id and b.meta.session_id == a.meta.parent_session_id:
        return True
    if b.meta.parent_session_id and a.meta.session_id == b.meta.parent_session_id:
        return True
    if a.files and b.files:
        inter = len(a.files & b.files)
        union = len(a.files | b.files)
        if union and inter / union >= min_jaccard:
            return True
    shared = a.tokens & b.tokens
    return len(shared) >= 2 and _within_window(a, b, DEFAULT_WINDOW_DAYS)


def build_threads(
    nodes: list[SessionNode],
    min_jaccard: float = DEFAULT_MIN_JACCARD,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[Thread]:
    """Union-find clustering: lineage links are hard edges, similarity edges
    additionally require the time window."""
    n = len(nodes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            a, b = nodes[i], nodes[j]
            linked = (a.meta.parent_session_id == b.meta.session_id) or (
                b.meta.parent_session_id == a.meta.session_id
            )
            if linked or (
                _within_window(a, b, window_days) and _similar(a, b, min_jaccard)
            ):
                union(i, j)

    threads: dict[int, list[SessionNode]] = {}
    for i, node in enumerate(nodes):
        threads.setdefault(find(i), []).append(node)
    return [
        Thread(sessions=sorted(g, key=lambda s: s.meta.updated_at or ""))
        for g in threads.values()
    ]


def describe_thread(t: Thread, indent: str = "  ") -> list[str]:
    """Human-readable lines for one thread."""
    last = t.last_active or "?"
    lines = [
        f"{len(t.sessions)} session(s) across {', '.join(t.clis)}, last active {last}"
    ]
    file_sets = [s.files for s in t.sessions if s.files]
    shared = set.intersection(*file_sets) if len(file_sets) > 1 else set()
    if shared:
        shown = sorted(shared)[:5]
        lines.append(f"{indent}shared files: {', '.join(shown)}")
    for s in t.sessions:
        title = s.meta.title.replace("\n", " ")[:52]
        parent = f" [child of {s.meta.parent_session_id[:16]}]" if s.meta.parent_session_id else ""
        origin = f" ({s.meta.origin})" if s.meta.origin else ""
        lines.append(
            f"{indent}- {s.meta.session_id[:24]} \"{title}\" "
            f"({s.meta.cli}{origin}, {(s.meta.updated_at or '?')[:10]}){parent}"
        )
    return lines

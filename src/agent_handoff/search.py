"""Full-text search over every discovered session — backed by a warm in-memory index.

Why an index at all: answering "where did I talk about X" needs one full parse
per session, which costs ~15 s across 450 sessions (and threading does not
help: the parsers are pure-Python JSON work, so they serialise on the GIL).
Paying that per query makes search unusable, so this module splits the two
concerns:

``build_index`` / ``warm_async``
    Walks the stores once and keeps, per session, the listing metadata *plus* a
    capped lowercase haystack. ``warm_async`` runs that in a single-flight
    background thread and returns immediately; the cockpit polls
    :func:`index_status` for the progress bar.

``search_cached`` (cockpit) / ``search`` (CLI)
    Scan the index only — no store reads at all, so a warm query is milliseconds.
    The CLI variant refreshes the index first (correctness over latency) and can
    report progress.

``mode="fast"``
    Metadata-only match driven by each parser's cheap listing: no body text, so
    it works even before the index is warm.

Constitution constraints honoured here: deterministic ranking (never depends on
which session finished indexing first), stdlib only, read-only with respect to
the CLI stores (the only bytes this writes land in ``~/.agenthandoff``, our own
state dir), and tolerant (one unreadable session never sinks the sweep).
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass

from agent_handoff.indexstore import IndexStore
from agent_handoff.model import RawSession, SessionMeta
from agent_handoff.parsers import available_parsers
from agent_handoff.parsers.base import Parser

# Scoring: a title hit beats a mention buried in turn 400.
_TITLE_W = 30
_FILE_W = 15
_ORIGIN_W = 12
_MODEL_W = 12
_PROVIDER_W = 8
_CWD_W = 6
_BODY_W = 10
MAX_HITS = 50

# Excerpt window: 40 chars of context each side of the match.
_EXCERPT_WIN = 40

# Memory guards. 120 KB of dialogue per session still covers what a human
# scrolls back to find (head + tail are kept for longer sessions); the entry cap
# bounds a pathological 5k-session machine at roughly 250 MB.
_HAYSTACK_CAP = 120_000
_CACHE_MAX_SESSIONS = 1_500

# How stale the cheap metadata listing may get before a fresh one is paid for.
# 20 s pairs with the cockpit's 30 s poll: a session that ended a moment ago
# should already be searchable.
_LISTING_TTL = 20.0

_WS = re.compile(r"\s+")


@dataclass
class SearchHit:
    cli: str
    session_id: str
    title: str
    cwd: str
    updated_at: str | None
    score: int  # higher = better (title > file/origin/model > cwd > body)
    excerpt: str = ""
    matched: str = ""  # hit surfaces, joined: "title+body"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchStats:
    mode: str = "full"
    scanned: int = 0  # index entries examined
    total: int = 0  # sessions the last listing saw (progress bar denominator)
    indexed: int = 0  # sessions covered by the index right now
    took_ms: int = 0
    index_state: str = "idle"  # idle | building | ready | failed
    truncated: bool = False  # more hits than `limit`
    refreshed: bool = False  # did this call pay for an index refresh


@dataclass
class _Entry:
    """Everything needed to match *and report* one session, kept in memory."""

    fingerprint: str
    meta: SessionMeta
    hay: str
    hay_l: str
    files: str
    files_l: str


_Key = tuple[str, str, str]  # (cli, session_id, source_path)


class _Index:
    """Session entries + build state. One lock, no threads of its own."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: OrderedDict[_Key, _Entry] = OrderedDict()
        self._state = "idle"
        self._done = 0
        self._total = 0
        self._error = ""

    @staticmethod
    def fingerprint(meta: SessionMeta) -> str:
        """Content identity as far as the listing reveals it.

        A session that grows always moves ``updated_at``. A store that rewrites
        history while keeping both timestamps identical is beyond what a
        read-only reader can detect — re-running ``handoff ui`` (or
        ``handoff search``) always re-checks, so nothing stays hidden for long.
        """
        return f"{meta.updated_at}|{meta.started_at}|{meta.title}"

    def get(self, key: _Key, fingerprint: str) -> _Entry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.fingerprint != fingerprint:  # stale: force a re-parse
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return entry

    def put(self, key: _Key, entry: _Entry) -> None:
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > _CACHE_MAX_SESSIONS:
                self._entries.popitem(last=False)

    def snapshot(self) -> list[tuple[_Key, _Entry]]:
        with self._lock:
            return list(self._entries.items())

    def prune(self, alive: set[_Key]) -> None:
        with self._lock:
            for key in [k for k in self._entries if k not in alive]:
                del self._entries[key]

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def begin_build(self, total: int) -> bool:
        """Single-flight gate: one cold pass per machine at a time."""
        with self._lock:
            if self._state == "building":
                return False
            self._state = "building"
            self._done = 0
            self._total = total
            self._error = ""
            return True

    def tick(self, n: int = 1) -> None:
        with self._lock:
            self._done = min(self._done + n, self._total)

    def end_build(self, state: str = "ready", error: str = "") -> None:
        with self._lock:
            self._state = state
            self._error = error

    def status(self, total: int | None = None) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "done": self._done,
                "total": total if total is not None else self._total,
                "indexed": len(self._entries),
                "error": self._error,
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._state = "idle"
            self._done = self._total = 0
            self._error = ""


_INDEX = _Index()
_STORE = IndexStore()
_LOCK = threading.Lock()
_LISTING: tuple[float, list[tuple[Parser, SessionMeta]]] = (0.0, [])


# -- store walking ------------------------------------------------------------


def _listing_fresh(max_age: float = _LISTING_TTL) -> list[tuple[Parser, SessionMeta]]:
    """Every readable (parser, meta) pair, briefly cached.

    Listing is cheap but not free (JSONL stores need a header scan per file),
    so it is cached for ``max_age`` seconds.
    """
    global _LISTING
    now = time.monotonic()
    with _LOCK:
        if _LISTING[1] and now - _LISTING[0] < max_age:
            return _LISTING[1]
        out: list[tuple[Parser, SessionMeta]] = []
        for parser in available_parsers():
            try:
                metas = parser.list_sessions()
            except OSError:  # a store that vanished mid-scan must not kill the sweep
                continue
            out.extend((parser, meta) for meta in metas)
        _LISTING = (now, out)
        return out


def _haystack_of(raw: RawSession) -> str:
    """Flatten the searchable dialogue of a session, capped.

    Tool *output* is excluded on purpose: the body is the human/agent dialogue,
    which is what a person searches for, and dumping megabytes of shell noise
    would blow the memory guard with junk. Touched file paths are indexed
    separately from ``files_touched``.
    """
    text = "\n".join(m.text for m in raw.messages if m.text)
    if len(text) > _HAYSTACK_CAP:
        # Keep both ends: the opening context and the latest turns are where a
        # lost session actually gets found.
        head = text[: _HAYSTACK_CAP // 2]
        tail = text[-(_HAYSTACK_CAP - len(head)) :]
        text = f"{head}\n…\n{tail}"
    return text


def _key_of(cli: str, meta: SessionMeta) -> _Key:
    """Identity of a session *as stored*.

    ``source_path`` is part of the key on purpose: archived roll copies can
    carry the same ``session_id`` with different content, and keying on
    (cli, sid) alone made them overwrite each other — silently dropping sessions
    from search and re-parsing the loser on every query (measured: 4 s steady
    state on this machine).

    The cli id comes from the *parser*, which owns the store, rather than from
    ``meta.cli`` (which a parser fills in itself) — otherwise a parser that
    leaves meta.cli unset disappears from cli-filtered search.
    """
    return (cli, meta.session_id, meta.source_path)


def _empty_entry(meta: SessionMeta) -> _Entry:
    """A marker for "this session yields no text".

    Without it, the ~7 % of sessions that parse to nothing (empty stores, a
    format a parser cannot read, a truncated roll) get re-parsed on *every*
    query — which is exactly the 4-5 s of JSON decoding the profile showed for
    the codex parser. The fingerprint still changes when the session grows, so
    a marker is automatically retried later.
    """
    return _Entry(
        fingerprint=_Index.fingerprint(meta),
        meta=meta,
        hay="",
        hay_l="",
        files="",
        files_l="",
    )


def _index_one(parser: Parser, meta: SessionMeta) -> bool:
    """Index a single session: memory, then disk, then the real parse.

    Returns True when text was actually read off disk or re-parsed (i.e. the
    caller paid for work), False on a memory hit.
    """
    key = _key_of(parser.cli, meta)
    fingerprint = _Index.fingerprint(meta)
    if _INDEX.get(key, fingerprint) is not None:
        return False
    stored = _STORE.get(meta.cli, meta.session_id, meta.source_path, fingerprint)
    if stored is not None:
        hay, files = stored
        _INDEX.put(
            key,
            _Entry(
                fingerprint=fingerprint,
                meta=meta,
                hay=hay,
                hay_l=hay.casefold(),
                files=files,
                files_l=files.casefold(),
            ),
        )
        return True
    try:
        raw = parser.load(meta.session_id)
    except (OSError, ValueError):  # tolerant: one bad session must not sink the sweep
        marker = _empty_entry(meta)
        _INDEX.put(key, marker)
        _STORE.put(meta.cli, meta.session_id, meta.source_path, marker.fingerprint, "", "")
        return False
    if raw is None:
        marker = _empty_entry(meta)
        _INDEX.put(key, marker)
        _STORE.put(meta.cli, meta.session_id, meta.source_path, marker.fingerprint, "", "")
        return False
    hay = _haystack_of(raw)
    files = "\n".join(raw.files_touched)
    _INDEX.put(
        key,
        _Entry(
            fingerprint=fingerprint,
            meta=meta,
            hay=hay,
            hay_l=hay.casefold(),
            files=files,
            files_l=files.casefold(),
        ),
    )
    _STORE.put(meta.cli, meta.session_id, meta.source_path, fingerprint, hay, files)
    return True


def _refresh(cli: str | None, on_progress=None) -> int:
    """Walk the stores and index anything new/changed. Returns sessions visited.

    The progress counters belong to whoever won ``begin_build``: a second,
    concurrent refresh still contributes entries to the shared cache, but it
    must not double-count or end someone else's build.
    """
    pairs = _listing_fresh()
    if cli:
        pairs = [(p, m) for p, m in pairs if p.cli == cli]
    owner = _INDEX.begin_build(len(pairs))
    done = 0
    t0 = time.monotonic()
    try:
        for parser, meta in pairs:
            _index_one(parser, meta)
            done += 1
            if owner:
                _INDEX.tick()
                if on_progress:
                    on_progress(done, len(pairs))
        if owner:
            _INDEX.prune({_key_of(p.cli, m) for p, m in _listing_fresh()})
    except Exception as exc:  # pragma: no cover - never leave the state stuck
        if owner:
            _INDEX.end_build("failed", f"{type(exc).__name__}: {exc}")
        raise
    if owner:
        _INDEX.end_build("ready")
        _STORE.note(
            {
                "sessions": done,
                "seconds": round(time.monotonic() - t0, 2),
                "persisted": _STORE.available,
            }
        )
    return done


def build_index(cli: str | None = None, on_progress=None) -> dict:
    """Blocking refresh (CLI correctness mode, tests). Idempotent when warm."""
    _refresh(cli, on_progress)
    return _INDEX.status()


def warm_async(cli: str | None = None) -> dict:
    """Start a background refresh if none is running. Never blocks the caller."""
    status = _INDEX.status()
    if status["state"] == "building":
        return status
    # Force a fresh listing so sessions created after startup get found.
    global _LISTING
    with _LOCK:
        _LISTING = (0.0, [])

    def run() -> None:
        try:
            _refresh(cli)
        except Exception as exc:  # pragma: no cover - _refresh already records it
            _INDEX.end_build("failed", str(exc))

    threading.Thread(target=run, name="agenthandoff-index", daemon=True).start()
    return _INDEX.status()


def index_status() -> dict:
    """{state, done, total, indexed, error} + persistence facts.

    What the cockpit progress bar reads.
    """
    status = _INDEX.status()
    status.update(_STORE.stats())
    return status


def reset_index(disk: bool = True) -> None:
    """Drop everything (tests, or ``handoff search --reindex``)."""
    global _LISTING
    _INDEX.clear()
    if disk:
        _STORE.clear()
    with _LOCK:
        _LISTING = (0.0, [])


# -- matching -----------------------------------------------------------------


def _excerpt(text: str, needle_lower: str) -> str:
    idx = text.casefold().find(needle_lower)
    if idx == -1:
        return _WS.sub(" ", text[: 2 * _EXCERPT_WIN]).strip()
    lo = max(0, idx - _EXCERPT_WIN)
    window = text[lo : idx + max(len(needle_lower), 1) + _EXCERPT_WIN]
    return ("…" if lo > 0 else "") + _WS.sub(" ", window).strip()


def _match_meta(query: str, meta: SessionMeta) -> tuple[int, list[str], str]:
    """Score the cheap surfaces of a session; shared by both modes."""
    q = query.casefold()
    score, where, excerpt = 0, [], ""
    if q in meta.title.casefold():
        score += _TITLE_W
        where.append("title")
        excerpt = _excerpt(meta.title, q)
    if meta.model and q in meta.model.casefold():
        score += _MODEL_W
        where.append("model")
    if meta.origin and q in meta.origin.casefold():
        score += _ORIGIN_W
        where.append("origin")
    if meta.provider and q in meta.provider.casefold():
        score += _PROVIDER_W
        where.append("provider")
    if q in (meta.cwd or "").casefold():
        score += _CWD_W
        where.append("cwd")
    return score, where, excerpt


def _hit(meta: SessionMeta, score: int, where: list[str], excerpt: str) -> SearchHit:
    return SearchHit(
        cli=meta.cli,
        session_id=meta.session_id,
        title=meta.title,
        cwd=meta.cwd,
        updated_at=meta.updated_at,
        score=score,
        excerpt=excerpt,
        matched="+".join(where),
    )


def _order(hits: list[SearchHit]) -> list[SearchHit]:
    """Deterministic ranking: score desc, then recency, then identity."""
    return sorted(hits, key=lambda h: (-h.score, h.updated_at or "", h.cli, h.session_id))


def _scan_entries(query: str, cli: str | None) -> tuple[list[SearchHit], int]:
    """Match the query against the index only — zero store access."""
    q = query.casefold()
    hits: list[SearchHit] = []
    scanned = 0
    for key, entry in _INDEX.snapshot():
        if cli and key[0] != cli:
            continue
        scanned += 1
        meta = entry.meta
        score, where, excerpt = _match_meta(query, meta)
        if entry.files_l and q in entry.files_l:
            score += _FILE_W
            where.append("file")
            if not excerpt:
                excerpt = f"file: {_excerpt(entry.files, q)}"
        if entry.hay_l and q in entry.hay_l:
            score += _BODY_W
            where.append("body")
            if not excerpt:
                excerpt = _excerpt(entry.hay, q)
        if score:
            hits.append(_hit(meta, score, where, excerpt))
    return _order(hits), scanned


def _scan_listing_fast(query: str, cli: str | None) -> tuple[list[SearchHit], int]:
    """Match metadata only, straight off the listings (works cold)."""
    hits: list[SearchHit] = []
    count = 0
    for parser, meta in _listing_fresh():
        if cli and parser.cli != cli:
            continue
        count += 1
        score, where, excerpt = _match_meta(query, meta)
        if score:
            hits.append(_hit(meta, score, where, excerpt))
    return _order(hits), count


def search_cached(
    query: str,
    cli: str | None = None,
    limit: int = MAX_HITS,
    mode: str = "full",
) -> tuple[list[SearchHit], SearchStats]:
    """Search without ever touching a store: index (full) or listing (fast).

    This is what the cockpit calls on every keystroke. Results can only cover
    what is indexed, so the stats say exactly that and the UI shows the index
    progress rather than pretending a hit list is complete.
    """
    t0 = time.perf_counter()
    query = query.strip()
    status = _INDEX.status()
    if len(query) < 2:  # documented floor: 1-char queries match half the corpus
        return [], SearchStats(mode=mode, total=status["total"], indexed=status["indexed"],
                               index_state=status["state"])

    if mode == "fast":
        hits, scanned = _scan_listing_fast(query, cli)
    else:
        hits, scanned = _scan_entries(query, cli)

    return hits[:limit], SearchStats(
        mode=mode,
        scanned=scanned,
        total=status["total"] or scanned,
        indexed=status["indexed"],
        took_ms=int((time.perf_counter() - t0) * 1000),
        index_state=status["state"],
        truncated=len(hits) > limit,
    )


def search_with_stats(
    query: str,
    cli: str | None = None,
    limit: int = MAX_HITS,
    mode: str = "fast",
    on_progress=None,
    reindex: bool = False,
) -> tuple[list[SearchHit], SearchStats]:
    """CLI entry point: refresh coverage first when bodies are in scope.

    ``mode="fast"`` stays listing-driven (instant, titles/paths only) so
    ``handoff search --fast`` is usable while a big machine is still indexing.
    ``reindex=True`` throws the cache away first (``--reindex``), which is the
    escape hatch for "I edited a session's title and the store kept the clock".
    """
    t0 = time.perf_counter()
    query = query.strip()
    refreshed = False
    if reindex:
        reset_index()
    if len(query) >= 2 and mode != "fast":
        _refresh(cli, on_progress)
        refreshed = True
    hits, stats = search_cached(query, cli=cli, limit=limit, mode=mode)
    stats.refreshed = refreshed
    stats.took_ms += int((time.perf_counter() - t0) * 1000)
    return hits, stats


def search(
    query: str,
    cli: str | None = None,
    limit: int = MAX_HITS,
    mode: str = "fast",
    on_progress=None,
    reindex: bool = False,
) -> list[SearchHit]:
    """Back-compatible entry point: ranked hits only.

    Note the default: ``fast`` (metadata). The old default was "parse all 450
    sessions per query", which is why a search took 15 s; a CLI user who wants
    bodies says so with ``--body``.
    """
    hits, _ = search_with_stats(
        query, cli=cli, limit=limit, mode=mode, on_progress=on_progress, reindex=reindex
    )
    return hits


__all__ = [
    "MAX_HITS",
    "SearchHit",
    "SearchStats",
    "build_index",
    "index_status",
    "reset_index",
    "search",
    "search_cached",
    "search_with_stats",
    "warm_async",
]

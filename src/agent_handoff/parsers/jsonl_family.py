"""JSONL-family parsers for Claude Code and CodeBuddy session files.

Both CLIs append one JSON object per line under
``~/.claude/projects/<munged-cwd>/<sessionId>.jsonl`` and
``~/.codebuddy/projects/<munged-cwd>/<sessionId>.jsonl``.

The two dialects differ in where role/content/timestamp live:

* Claude Code: ``{"type": "user"|"assistant", "message": {...}, "timestamp": ISO}``
  plus ``{"type": "summary"}`` lines. Message payload holds ``role``/``content``.
* CodeBuddy:   ``{"type": "message", "role": ..., "content": [...], "timestamp": ms}``.

One configurable reader handles both; unknown line types are skipped so new
upstream fields never crash a capture.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta, TodoItem, ts_to_iso
from agent_handoff.parsers.base import Parser, as_text_blocks, read_jsonl


def _tail_rows(path: Path, max_bytes: int = 65536) -> list[dict]:
    """The last records of a JSONL file, without reading the whole thing.

    The newest timestamp lives at the end of a long transcript, and `stat().mtime`
    is not it: mtime is when the file was copied, restored or checked out.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
                handle.readline()  # drop the fragment of a partial line
            payload = handle.read()
    except OSError:
        return []
    rows: list[dict] = []
    for line in payload.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _mtime_iso(stamp: float) -> str | None:
    """Last resort dating: the filesystem, when the store recorded nothing."""
    if not stamp:
        return None
    return _iso(datetime.fromtimestamp(stamp, tz=timezone.utc))


def _record_stamp(rows: list[dict]) -> str | None:
    """Newest `timestamp` any record in `rows` carries."""
    stamps = [iso for row in rows if (iso := _iso(row.get("timestamp")))]
    return max(stamps) if stamps else None


def _iso(value) -> str | None:
    """Normalize ISO strings or epoch millis into ISO-8601 UTC."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        return ts_to_iso(value)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return None


_SUMMARY_REQ = re.compile(r"Primary Request[^:\uFF1A]*[:\uFF1A]\s*(.{4,160})")


def _summary_title(text: str) -> str:
    """Compacted sessions open with <conversation_history_summary>; the user's
    real intent survives in its Primary Request line."""
    m = _SUMMARY_REQ.search(text)
    if m:
        frag = m.group(1).strip().strip("*").strip()
        if frag:
            return frag[:80]
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("<", "Summary")):
            return line[:80]
    return ""


# Sessions whose transcript holds zero real user messages: internal tool loops
# (spawned browser/automation sub-agents). Products never list them as
# conversations, so the cockpit drops them from the listing too (still loadable
# by id for debugging).
_TOOLLOOP_TITLE = "工具循环会话（无用户消息）"

# ~/.qoder-cn (and ~/.qoder) is SHARED by the whole qoder family: the IDE's own
# chats live under <project>/transcript/ or in plain <project> dirs, while
# qoderwake team-groups/workers and qoderwork workspaces each create top-level
# project dirs named after the product. One listing must not mix families —
# the wake/work transcripts belong to their own CLI entries.
_FAMILY_MARKERS = ("qoderwake", "qoderwork")


def _family_of_path(root: Path, path: str) -> str | None:
    """Which qoder family a transcript belongs to, from the store dir name."""
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None
    for part in rel.parts:
        for family in _FAMILY_MARKERS:
            if family in part:
                return family
    return None

# Cache of absorbed add_user_message fragments per store, keyed by the store
# root and invalidated by the newest file mtime, so repeated dashboard loads do
# not rescan every real session just to de-duplicate a handful of turn fragments.
_QODER_ABSORB_CACHE: dict = {}
_ABSORB_SCAN_CAP_BYTES = 60_000_000


def _parse_iso_local(iso):
    """Parse an ISO timestamp (qoder mixes +00:00 strings); None on failure."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


class JsonlSessionParser(Parser):
    """Shared reader for Claude Code / CodeBuddy / compatible JSONL dialects."""

    cli = "jsonl"
    projects_dirname: str = ""  # ".claude" / ".codebuddy"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (home() / self.projects_dirname / "projects")
        # sid -> every file that reports it, filled by list_sessions().
        self._index: dict[str, list[Path]] = {}

    def available(self) -> bool:
        return self.root.is_dir()

    # -- discovery ----------------------------------------------------------

    def _iter_jsonl(self) -> list[Path]:
        if not self.available():
            return []
        return sorted(p for p in self.root.rglob("*.jsonl") if p.is_file())

    def _group_files(self, paths: list[Path], sid: str) -> list[Path]:
        """Rank a session's files: canonical transcript first, companions after."""

        def rank(path: Path) -> tuple[int, int]:
            score = 0
            if path.stem == sid:
                score = 3
            elif path.parent.name == sid or path.name == "session.jsonl":
                score = 2
            elif path.name.startswith("agent-"):
                score = 1  # sub-agent transcript, part of the session but not its head
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            return (score, size)

        return sorted(paths, key=rank, reverse=True)

    def list_sessions(self) -> list[SessionMeta]:
        """One entry per session, even when the store splits it over many files.

        Reading the id out of each record and then emitting per-file entries made
        a session with sub-agent transcripts appear several times, and left
        `load()` looking for a file name that does not exist. Grouping first fixes
        both, and keeps `source_path` pointing at the canonical transcript.
        """
        groups: dict[str, list[Path]] = {}
        for path in self._iter_jsonl():
            sid = self._peek_id(path)
            if sid:
                groups.setdefault(sid, []).append(path)
        self._index = groups

        metas: list[SessionMeta] = []
        for sid, paths in groups.items():
            meta = self._peek(self._group_files(paths, sid)[0])
            if meta is not None:
                meta.session_id = sid
                metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def _peek_id(self, path: Path) -> str:
        """Session id as the store reports it, falling back to the file stem."""
        for row in read_jsonl(path, limit=10):
            sid = row.get("sessionId") or row.get("session_id")
            if sid:
                return str(sid)
        return path.stem

    def _origin(self) -> str | None:
        """Store directory (e.g. .qoderwork vs .qoderworkcn) = account scope."""
        name = self.root.parent.name
        return name if name.startswith(".") else None

    def _peek(self, path: Path) -> SessionMeta | None:
        """Scan the head of a roll for identity + the first real title.

        limit=800 because compaction/quest transcripts bury the first real turn
        under hundreds of tool-hint/meta rows (measured: a 13 MB compacted roll
        keeps its summary at line 487).
        """
        rows = read_jsonl(path, limit=800)
        if not rows:
            return None
        cwd = ""
        session_id = path.stem
        title = ""
        ai_title = ""
        started = updated = None
        for r in rows:
            cwd = cwd or (r.get("cwd") or "")
            session_id = r.get("sessionId") or session_id
            # Official title rows (workbuddy/codebuddy write an AI title as a
            # dedicated row, usually near the top). Track them separately: they
            # outrank the first-user-message guess even when found AFTER the
            # first user turn, so the scan must not break on the user turn.
            if r.get("type") == "ai-title" and r.get("aiTitle"):
                ai_title = ai_title or str(r["aiTitle"])[:80]
            if r.get("type") == "summary" and r.get("summary"):
                title = title or str(r["summary"])[:80]
            role, text, _tools = self._row_content(r)
            if role == "user" and text and not self.is_noise(text):
                started = _iso(r.get("timestamp")) or started
                if not title:
                    if text.startswith("<conversation_history_summary"):
                        title = _summary_title(text)
                    else:
                        title = text[:80]
                if ai_title:
                    break
        tail = _tail_rows(path)
        # The official ai-title row is appended asynchronously near the END of
        # the roll, after the conversation; a head-only scan misses it. It is
        # the product's own title, so it outranks the first-user-message guess.
        for r in tail:
            if r.get("type") == "ai-title" and r.get("aiTitle"):
                ai_title = str(r["aiTitle"])[:80]
                break
        title = ai_title or title
        updated = _record_stamp(rows) or _record_stamp(tail)
        if updated is None:
            # Only a store that records no timestamps at all may be dated by its
            # filesystem - and then the date means "copied", not "last turn".
            try:
                updated = _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
            except OSError:
                updated = None
        if not title:
            # No user text and no official title row: a pure tool loop (usually
            # a spawned browser/automation sub-agent). Say so honestly instead of
            # leaking a bare short id that looks like a parsing failure.
            title = _TOOLLOOP_TITLE
        return SessionMeta(
            cli=self.cli,
            session_id=session_id,
            title=title,
            cwd=cwd,
            started_at=started,
            updated_at=updated,
            source_path=str(path),
            origin=self._origin(),
        )

    def load(self, session_id: str) -> RawSession | None:
        paths = self._resolve_group(session_id)
        if not paths:
            return None
        return self._load_paths(paths, session_id)

    def peek_needs_reply(self, session_id: str) -> bool | None:
        """Tail-scan the canonical transcript: is the last real turn a user one?

        Runs for every row of the session list, so it must stay cheap: it only
        reads the cached ``_index`` (populated by list_sessions) and the last
        16 KB of the canonical file. It deliberately avoids ``_resolve_group``
        because that can fall back to a full-store rglob scan, which — run once
        per listed session — stalls the whole listing.
        """
        paths = self._index.get(session_id)
        if not paths:
            return None
        head = self._group_files(paths, session_id)[0]
        rows = _tail_rows(head, max_bytes=16384)
        for r in reversed(rows):
            role, text, _tools = self._row_content(r)
            if role in ("user", "assistant") and text and not self.is_noise(text):
                return role == "user"
        return None

    def _resolve_group(self, session_id: str) -> list[Path]:
        """All files that make up one session; cheap and storage-layout agnostic."""
        if session_id.endswith(".jsonl"):  # a caller passed a path
            one = Path(session_id)
            return [one] if one.exists() else []
        cached = self._index.get(session_id)
        if cached:
            return self._group_files(cached, session_id)
        # Index is empty when load() is called without a prior list_sessions()
        # (e.g. the cockpit detail endpoint creates a fresh parser per request).
        # Populate it so sub-agent files (agent-*.jsonl) are reachable by the
        # session id recorded inside their records, not just by filename.
        if not self._index:
            self.list_sessions()
            cached = self._index.get(session_id)
            if cached:
                return self._group_files(cached, session_id)
        found = [
            p
            for p in self._iter_jsonl()
            if p.stem == session_id or p.parent.name == session_id
        ]
        if found:
            return self._group_files(found, session_id)
        return []

    # -- extraction ---------------------------------------------------------

    def _row_content(self, row: dict) -> tuple[str, str, list[dict]]:
        """Return (role, plain_text, tool_blocks) for one JSONL row."""
        rtype = row.get("type")
        if rtype not in (None, "message", "user", "assistant"):
            return "", "", []
        inner = row.get("message") if isinstance(row.get("message"), dict) else {}
        role = row.get("role") or inner.get("role") or ""
        content = row.get("content") if row.get("content") is not None else inner.get("content")
        text, tools = as_text_blocks(content)
        return role, self.clean_text(text), tools

    @staticmethod
    def _row_billing(row: dict) -> tuple[str, dict]:
        """(model, token counters) recorded on one row, dialect-tolerant.

        CodeBuddy/WorkBuddy hang them under ``providerData`` (``model`` plus
        ``rawUsage``/``usage``); the Claude-Code dialect puts them on the inner
        ``message`` object. Only assistant turns carry billing.
        """
        pd = row.get("providerData")
        src = pd if isinstance(pd, dict) else {}
        inner = row.get("message") if isinstance(row.get("message"), dict) else {}
        model = src.get("model") or inner.get("model") or ""
        usage = src.get("rawUsage") or src.get("usage") or inner.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        details = usage.get("completion_tokens_details")
        details = details if isinstance(details, dict) else {}
        pdetails = usage.get("prompt_tokens_details")
        pdetails = pdetails if isinstance(pdetails, dict) else {}
        tokens = {
            "in": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "out": usage.get("completion_tokens") or usage.get("output_tokens"),
            "reasoning": details.get("reasoning_tokens"),
            "cache_read": pdetails.get("cached_tokens") or usage.get("cache_read_input_tokens"),
        }
        return str(model) if model else "", {k: int(v) for k, v in tokens.items() if v is not None}

    def _tool_name_input(self, block: dict) -> tuple[str, dict]:
        name = block.get("name") or block.get("tool") or block.get("toolName") or "tool"
        tool_input = block.get("input")
        if not isinstance(tool_input, dict):
            inner = block.get("state") or {}
            tool_input = inner.get("input") if isinstance(inner, dict) else {}
        return str(name), (tool_input if isinstance(tool_input, dict) else {})

    @staticmethod
    def _subagent_label(path: Path) -> str | None:
        """Which sub-agent a transcript belongs to, or None for the main file.

        Sub-agent rolls live under ``<session>/subagents/`` and are named
        ``agent-<hash>.jsonl`` (codebuddy/workbuddy); the main conversation is the
        sibling ``<session>.jsonl``. Tagging lets the UI show sub-agent work under
        the parent instead of a flat interleaved dump.
        """
        if path.parent.name == "subagents" or path.name.startswith("agent-"):
            return path.stem
        return None

    def _load_paths(self, paths: list[Path], session_id: str) -> RawSession:
        """Merge a session's files: main transcript first, companions after."""
        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        todos: list[TodoItem] = []
        cwd = ""
        title = ""
        started = None
        newest_at: str | None = None
        newest_mtime = 0.0
        seen_ids: set[tuple[str, str]] = set()

        for path in paths:
            try:
                newest_mtime = max(newest_mtime, path.stat().st_mtime)
            except OSError:
                continue
            sub_label = self._subagent_label(path)
            for row in read_jsonl(path):
                if row.get("type") == "summary":
                    continue
                cwd = cwd or (row.get("cwd") or "")
                at = _iso(row.get("timestamp"))
                started = started or at
                if at and (newest_at is None or at > newest_at):
                    newest_at = at

                role, text, tool_blocks = self._row_content(row)
                if not role:
                    continue
                for tb in tool_blocks:
                    name, tool_input = self._tool_name_input(tb)
                    tools[name] += 1
                    for p in self.extract_paths(tool_input):
                        files[p] += 1
                    if name in ("TodoWrite", "todo_write", "TaskCreate") and isinstance(
                        tool_input.get("todos"), list
                    ):
                        for t in tool_input["todos"]:
                            if isinstance(t, dict) and t.get("content"):
                                todos.append(
                                    TodoItem(
                                        content=str(t["content"]),
                                        status=str(t.get("status") or "pending"),
                                        priority=str(t.get("priority") or ""),
                                    )
                                )
                if text and not self.is_noise(text):
                    key = (role, text)
                    if key in seen_ids:
                        continue  # the same turn mirrored into a companion file
                    seen_ids.add(key)
                    if role == "user" and not title:
                        title = text[:80]
                    model, tokens = self._row_billing(row)
                    messages.append(
                        Message(
                            role=role,
                            text=text,
                            at=at,
                            model=model or None,
                            tokens_in=tokens.get("in"),
                            tokens_out=tokens.get("out"),
                            tokens_reasoning=tokens.get("reasoning"),
                            subagent=sub_label,
                        )
                    )

        if len({m.at for m in messages if m.at}) > 1 and all(m.at for m in messages):
            messages.sort(key=lambda m: m.at or "")  # merge companions chronologically

        meta = SessionMeta(
            cli=self.cli,
            session_id=session_id,
            title=title or session_id,
            cwd=cwd,
            started_at=started,
            updated_at=newest_at or _mtime_iso(newest_mtime),
            source_path=str(paths[0]),
            origin=self._origin(),
        )
        return self.build_raw(meta, messages, todos, files, tools)


    def usage(self, session_id: str) -> dict | None:
        """Per-model token accounting aggregated from the turns themselves.

        Works for any dialect that records per-turn billing (codebuddy's
        providerData.rawUsage, the Claude-Code message.usage). Returns the same
        shape the dedicated stores (zcode/codex) produce, with latency columns
        left null because flat JSONL stores time nothing that fine.
        """
        raw = self.load(session_id)
        if raw is None:
            return None
        agg: dict[str, dict] = {}
        for m in raw.messages:
            if not m.model or (m.tokens_in is None and m.tokens_out is None):
                continue
            a = agg.setdefault(
                m.model,
                {"calls": 0, "tokens_in": 0, "tokens_out": 0, "reasoning": 0},
            )
            a["calls"] += 1
            a["tokens_in"] += m.tokens_in or 0
            a["tokens_out"] += m.tokens_out or 0
            a["reasoning"] += m.tokens_reasoning or 0
        if not agg:
            return None
        models = []
        tot_in = tot_out = tot_calls = 0
        for model, a in sorted(agg.items(), key=lambda kv: -kv[1]["tokens_out"]):
            models.append(
                {
                    "model": model,
                    "calls": a["calls"],
                    "tokens_in": a["tokens_in"],
                    "tokens_out": a["tokens_out"],
                    "reasoning": a["reasoning"],
                    "cache_write": 0,
                    "cache_read": 0,
                    "avg_ttft_ms": None,
                    "tok_per_s": None,
                }
            )
            tot_in += a["tokens_in"]
            tot_out += a["tokens_out"]
            tot_calls += a["calls"]
        return {
            "models": models,
            "totals": {"calls": tot_calls, "tokens_in": tot_in, "tokens_out": tot_out},
        }


class ClaudeCodeParser(JsonlSessionParser):
    cli = "claude"
    projects_dirname = ".claude"


class _CodebuddyHybridParser(JsonlSessionParser):
    """Codebuddy uses two layouts under ``<root>/<project>/``:

    1. **Flat**: ``<project>/<session-id>.jsonl`` — standalone session.
    2. **Nested**: ``<project>/<session-dir>/subagents/agent-*.jsonl`` —
       sub-agent transcripts belonging to the directory (the real session).

    The directory name in layout 2 is the session ID; sub-agent files carry
    an internal ``sessionId`` that is runtime context (the parent that
    spawned them), not the file's own identity.  Grouping by the embedded
    ID split one directory's agents into separate "sessions" and merged
    unrelated directories — both wrong.
    """

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        metas: list[SessionMeta] = []
        seen: set[str] = set()

        # Layout 2: session dirs with subagents/ children.
        for subagents_dir in sorted(self.root.rglob("subagents")):
            session_dir = subagents_dir.parent
            sid = session_dir.name
            if sid in seen or not sid.replace("-", "").isalnum():
                continue
            seen.add(sid)
            agent_files = sorted(subagents_dir.glob("*.jsonl"))
            if not agent_files:
                continue
            # The main transcript usually also exists as a flat file next to the
            # session dir; it carries the real user dialogue (sub-agent files are
            # side work), so let it lead the metadata scan.
            flat = session_dir.parent / (sid + ".jsonl")
            scan_files = [flat] + agent_files if flat.is_file() else agent_files
            meta = self._cb_peek_dir(sid, agent_files, scan_files)
            if meta:
                metas.append(meta)

        # Layout 1: flat .jsonl files that are NOT inside a session dir's
        # subagents/ — each is its own standalone session.
        for path in sorted(self.root.rglob("*.jsonl")):
            if not path.is_file():
                continue
            # Skip files inside subagents/ — those belong to layout 2.
            if path.parent.name == "subagents":
                continue
            sid = self._peek_id(path)
            if sid in seen:
                continue
            seen.add(sid)
            meta = self._peek(path)
            if meta is not None:
                meta.session_id = sid
                metas.append(meta)

        # Agents (codebuddy background jobs) carry the official session name in
        # jobs/<shortid>/state.json; the sessionId field links the job to the
        # conversation (it may differ from the job's own short id).
        titles = self._job_titles()
        for m in metas:
            jt = titles.get(m.session_id)
            if jt:
                m.title = jt
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def _job_titles(self) -> dict[str, str]:
        """sessionId -> official agent name from ``jobs/*/state.json``.

        These are the titles codebuddy's own UI shows for its agents — the
        highest-priority source, above ai-title rows and first-user fallback.
        """
        out: dict[str, str] = {}
        jobs_dir = self.root.parent / "jobs"
        if not jobs_dir.is_dir():
            return out
        for state in jobs_dir.glob("*/state.json"):
            try:
                d = json.loads(state.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError):
                continue
            sid = d.get("sessionId")
            name = d.get("name")
            if sid and name:
                out[sid] = str(name)[:80]
        return out

    def _cb_peek_dir(
        self, sid: str, agent_files: list[Path], scan_files: list[Path] | None = None
    ) -> SessionMeta | None:
        """Cheap metadata scan for one session dir.

        ``scan_files`` defaults to the sub-agent files; callers pass the flat
        main transcript first when one exists so its user dialogue wins the title.
        """
        cwd = ""
        title = ""
        ai_title = ""
        started = updated = None
        stamp_files: list[Path] = []
        for path in (scan_files or agent_files):
            stamp_files.append(path)
            for r in read_jsonl(path, limit=800):
                cwd = cwd or (r.get("cwd") or "")
                if r.get("type") == "ai-title" and r.get("aiTitle"):
                    ai_title = ai_title or str(r["aiTitle"])[:80]
                if r.get("type") == "summary" and r.get("summary"):
                    title = title or str(r["summary"])[:80]
                role, text, _tools = self._row_content(r)
                if role == "user" and text and not self.is_noise(text):
                    if not title:
                        if text.startswith("<conversation_history_summary"):
                            title = _summary_title(text)
                        else:
                            title = text[:80]
                    started = started or _iso(r.get("timestamp"))
                stamp = _iso(r.get("timestamp"))
                if stamp and (updated is None or stamp > updated):
                    updated = stamp
            if title and cwd:
                break
        title = ai_title or title
        if updated is None:
            try:
                mt = max(p.stat().st_mtime for p in (stamp_files or agent_files))
                updated = _iso(datetime.fromtimestamp(mt, tz=timezone.utc))
            except (OSError, ValueError):
                pass
        head = (scan_files or agent_files)[0] if (scan_files or agent_files) else agent_files[0]
        return SessionMeta(
            cli=self.cli,
            session_id=sid,
            title=title or _TOOLLOOP_TITLE,
            cwd=cwd,
            started_at=started,
            updated_at=updated,
            source_path=str(head),
            origin=self._origin(),
        )

    def load(self, session_id: str) -> RawSession | None:
        if session_id.endswith(".jsonl"):
            one = Path(session_id)
            return self._load_paths([one], session_id) if one.exists() else None

        # Layout 2: session dir with subagents/. The flat main transcript (the
        # real user dialogue) sits next to the dir and MUST be loaded together
        # with the sub-agent files — reading only the sub-agents silently drops
        # the whole main conversation.
        session_dir = self._find_session_dir(session_id)
        if session_dir is not None:
            paths: list[Path] = []
            flat = session_dir.parent / (session_id + ".jsonl")
            if flat.is_file():
                paths.append(flat)  # canonical head: ranks above agent-* files
            subagents_dir = session_dir / "subagents"
            if subagents_dir.is_dir():
                paths.extend(sorted(subagents_dir.glob("*.jsonl")))
            if paths:
                raw = self._load_paths(paths, session_id)
                if raw is not None:
                    jt = self._job_titles().get(session_id)
                    if jt:
                        raw.meta.title = jt
                return raw

        # Layout 1: flat file — fall back to the base class resolver.
        raw = super().load(session_id)
        if raw is not None:
            jt = self._job_titles().get(session_id)
            if jt:
                raw.meta.title = jt
        return raw

    def _find_session_dir(self, session_id: str) -> Path | None:
        """Locate a session dir by name under any project."""
        if not self.available():
            return None
        for subagents_dir in self.root.rglob("subagents"):
            if subagents_dir.parent.name == session_id:
                return subagents_dir.parent
        return None


class CodebuddyParser(_CodebuddyHybridParser):
    cli = "codebuddy"
    projects_dirname = ".codebuddy"


class CodebuddyCnParser(JsonlSessionParser):
    """CodeBuddy CN edition — same layout under ~/.codebuddycn."""

    cli = "codebuddy-cn"
    projects_dirname = ".codebuddycn"


class WorkbuddyParser(_CodebuddyHybridParser):
    """WorkBuddy — codebuddy-shaped transcripts plus a SQLite title index.

    Layout mirrors codebuddy (flat ``<sid>.jsonl`` + ``<sid>/subagents/``), so
    the hybrid reader is reused as-is. What codebuddy lacks is a durable title:
    workbuddy keeps one in ``~/.workbuddy/workbuddy.db`` (``sessions.title`` /
    ``custom_title``), so list_sessions() overlays it after the heuristic scan.
    Titles like ``@long-text:"..."`` are truncated quote markers and are reduced
    to the quoted head.
    """

    cli = "workbuddy"
    projects_dirname = ".workbuddy"

    def usage(self, session_id: str) -> dict | None:
        """Turn-aggregated usage plus the store's own quota/credit ledger.

        workbuddy.db.session_usage records per-session context spend (used/size)
        and per-model credit costs (credit_json: model-hash -> credits). Both are
        attached under `credits`/`quota` — that is the billing layer the raw
        turns cannot express.
        """
        result = super().usage(session_id)
        try:
            import json as _json
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if db.is_file():
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                try:
                    row = conn.execute(
                        "SELECT used, size, credit_json FROM session_usage WHERE session_id=?",
                        (session_id,),
                    ).fetchone()
                finally:
                    conn.close()
                if row:
                    used, size, credit_raw = row
                    if result is None:
                        result = {
                            "models": [],
                            "totals": {"calls": 0, "tokens_in": 0, "tokens_out": 0},
                        }
                    result["quota"] = {"used": used, "size": size}
                    if credit_raw:
                        with contextlib.suppress(ValueError):
                            result["credits"] = _json.loads(credit_raw)
        except Exception:  # ledger missing — turn-based usage still stands
            pass
        return result

    def list_sessions(self) -> list[SessionMeta]:
        metas = super().list_sessions()  # already carries jsonl ai-title rows
        db = self._db_titles()
        for m in metas:
            # The AI-generated title written into the transcript is the title
            # the product shows; the db sessions.title (often the raw first
            # prompt) only fills gaps.
            if not m.title or m.title == m.session_id or len(m.title) <= 8:
                t = db.get(m.session_id)
                if t:
                    m.title = t
        return metas

    def _db_titles(self) -> dict[str, str]:
        """session_id -> display title from workbuddy.db (read-only)."""
        try:
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if not db.is_file():
                return {}
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT id, title, custom_title, deleted_at FROM sessions"
                ).fetchall()
            finally:
                conn.close()
            out: dict[str, str] = {}
            for sid, title, custom, deleted in rows:
                if deleted:
                    continue
                t = self._clean_title(custom or title)
                if sid and t:
                    out[str(sid)] = t
            return out
        except Exception:  # DB locked / schema drift — heuristic titles stand
            return {}

    @staticmethod
    def _clean_title(raw) -> str:
        if not raw:
            return ""
        t = str(raw).strip()
        # "@long-text:\"...\" <long_text_quote>..." is a truncation marker;
        # keep the quoted head so the list shows real content, not the wrapper.
        if t.startswith("@long-text:"):
            body = t.split(":", 1)[1].strip()
            if body.startswith('"'):
                end = body.find('"', 1)
                if end > 0:
                    body = body[1:end]
            t = body.split("<long_text_quote>")[0].strip()
        return t[:120]


class _QoderworkSharedMixin:
    """The work CLI also lands workspace sessions in the shared qoder store
    (~/.qoder/projects/<...qoderwork-workspace-...>); they belong to the work
    CLI entry, not to the IDE one. Overriding ``_iter_jsonl`` keeps listing
    and loading on the same file set.
    """

    shared_store = ".qoder"
    workspace_marker = "qoderwork-workspace"

    def _shared_root(self) -> Path | None:
        # ``self.root`` is either ``<home>/<hidden-store>/projects`` (production)
        # or the hidden-store dir itself (tests with an explicit root).
        candidates = (self.root.parent.parent, self.root.parent)
        for base in candidates:
            shared = base / self.shared_store / "projects"
            if shared.is_dir() and shared.resolve() != self.root.resolve():
                return shared
        return None

    def _iter_jsonl(self) -> list[Path]:
        paths = list(super()._iter_jsonl())
        shared = self._shared_root()
        if shared is not None:
            for p in shared.rglob("*.jsonl"):
                if self.workspace_marker in str(p):
                    paths.append(p)
        return sorted(set(paths))


class QoderworkParser(_QoderworkSharedMixin, JsonlSessionParser):
    """Qoderwork — Claude-Code-style JSONL under ~/.qoderwork/projects."""

    cli = "qoderwork"
    projects_dirname = ".qoderwork"


class QoderworkCnParser(_QoderworkSharedMixin, JsonlSessionParser):
    """Qoderwork CN — a separate login (second account) under ~/.qoderworkcn.

    Variant directories of the same product are distinct account scopes:
    the user may run one account per variant (verified live: each carries
    its own .auth/machine_id). ``origin`` records which store a session
    came from so multi-account usage stays distinguishable.
    """

    cli = "qoderwork-cn"
    projects_dirname = ".qoderworkcn"
    shared_store = ".qoder-cn"
    workspace_marker = "qoderworkcn-workspace"


class QwenworkParser(JsonlSessionParser):
    """Qwen Work CN — same layout under ~/.qwenworkcn/projects."""

    cli = "qwenwork"
    projects_dirname = ".qwenworkcn"


class QodercnIdeParser(JsonlSessionParser):
    """Qoder CN IDE — shared session store at ~/.qoder-cn/projects.

    One root serves the whole qoder-cn product family: the IDE itself, the
    qoderworkcn CLI, and qoderwake workspaces all land their sessions here
    (project dirs are munged cwd names, so the origin is visible per
    session). Line format is the Claude-Code dialect.

    Quest tasks carry real titles ("驾驶舱便捷启停说明") that never reach the
    JSONL transcripts; they live in the IDE's global state DB
    (``%APPDATA%/QoderCN/User/globalStorage/state.vscdb``, key
    ``aicoding.questTaskListSnapshot``).  When that snapshot is readable the
    task title wins over the first-user-message heuristic.
    """

    cli = "qodercn-ide"
    projects_dirname = ".qoder-cn"
    # Variant-specific locations: the IDE's global state DB (quest titles) and
    # the matching qoderwake store (board titles for qs_* sessions).
    appdata_product = "QoderCN"
    wake_store = ".qoderwake-cn"

    # Interactive chat writes one `add_user_message` fragment file per user turn.
    # Consecutive fragments in one cwd are one conversation; listing each as a
    # separate session fragments the chat (the IDE shows them unified). Merge
    # fragments whose starts are within this window.
    _FRAG_GAP_MINUTES = 60

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root)
        self._quest_titles: dict[str, str] | None = None
        self._frag_ids: set[str] = set()
        self._frag_groups: dict[str, list[str]] = {}

    def _peek(self, path: Path):
        meta = super()._peek(path)
        if meta is not None:
            # Detect qoder per-turn fragments from the early session_meta row.
            for r in read_jsonl(path, limit=6):
                if r.get("type") == "session_meta":
                    st = (r.get("data") or {}).get("content", {}).get("session_type")
                    if st == "add_user_message":
                        self._frag_ids.add(meta.session_id)
                    break
        return meta

    def _list_all(self) -> list[SessionMeta]:
        """Every session in the shared store, before family filtering.

        The wake/work families live in the same store, so their parsers reuse
        this pipeline (fragment merge/absorb, official titles) and filter the
        other direction.
        """
        self._frag_ids = set()
        self._frag_groups = {}
        metas = super().list_sessions()
        titles = self._load_quest_titles()
        wake = self._wake_titles()
        for m in metas:
            t = titles.get(m.session_id) or wake.get(m.session_id)
            if t:
                m.title = t

        # Absorb fragments whose single user message already lives inside a real
        # (task/uuid) session — those are redundant turn-echoes of a conversation
        # that is listed in its own right. Then merge whatever fragments remain.
        absorbed = self._absorbed_fragment_ids(metas)

        # Merge consecutive add_user_message fragments into one conversation so
        # a chat with N turns is one entry, not N.
        frags = sorted(
            (m for m in metas if m.session_id in self._frag_ids and m.session_id not in absorbed),
            key=lambda m: m.started_at or m.updated_at or "",
        )
        reals = [m for m in metas if m.session_id not in self._frag_ids]
        merged: list[SessionMeta] = []
        group: list[SessionMeta] = []

        def flush() -> None:
            if not group:
                return
            if len(group) >= 2:
                rep = group[0]
                self._frag_groups[rep.session_id] = [g.session_id for g in group]
                rep.updated_at = max((g.updated_at or "" for g in group), default=rep.updated_at)
                rep.title = f"{rep.title}（{len(group)} 轮对话）"
                merged.append(rep)
            else:
                merged.append(group[0])

        for m in frags:
            if group and (m.cwd or "") == (group[-1].cwd or "") and self._within_gap(group[-1], m):
                group.append(m)
            else:
                flush()
                group = [m]
        flush()

        out = reals + merged
        # A transcript with zero real user messages is an internal tool loop
        # (browser/automation sub-agent run), not a conversation — the product
        # UI never lists them, so neither do we. Still loadable by id.
        out = [m for m in out if m.title != _TOOLLOOP_TITLE]
        out.sort(key=lambda m: m.updated_at or "", reverse=True)
        return out

    def list_sessions(self) -> list[SessionMeta]:
        """The IDE's own chats only: wake/work families leave the shared store
        for their own CLI entries (still deep-linkable by id via load())."""
        out = [
            m
            for m in self._list_all()
            if _family_of_path(self.root, m.source_path) is None
        ]
        return out

    def _within_gap(self, a: SessionMeta, b: SessionMeta) -> bool:
        ta = _parse_iso_local(a.started_at or a.updated_at)
        tb = _parse_iso_local(b.started_at or b.updated_at)
        if ta is None or tb is None:
            return False
        return abs((tb - ta).total_seconds()) <= self._FRAG_GAP_MINUTES * 60

    def _fragment_user_text(self, session_id: str) -> str:
        """The single user message of an add_user_message fragment file."""
        for path in self._resolve_group(session_id):
            for r in read_jsonl(path, limit=8):
                role, text, _tools = self._row_content(r)
                if role == "user" and text:
                    return text.strip()
        return ""

    def _absorbed_fragment_ids(self, metas: list[SessionMeta]) -> set:
        """Fragment session ids whose user text already exists in a real session.

        qoder writes every user turn as an ``add_user_message`` fragment AND keeps
        the same message inside the task/uuid conversation. Listing both shows one
        conversation twice; the fragment is the redundant copy, so it is absorbed.
        Result is cached per store (invalidated by newest file mtime) and the scan
        is byte-capped so a large store cannot stall a dashboard load.
        """
        frag_metas = [m for m in metas if m.session_id in self._frag_ids]
        if not frag_metas:
            return set()
        try:
            sig = max(p.stat().st_mtime for p in self._iter_jsonl())
        except (OSError, ValueError):
            sig = None
        cache_key = str(self.root)
        cached = _QODER_ABSORB_CACHE.get(cache_key)
        if cached is not None and cached[0] == sig:
            return cached[1]

        frag_texts: dict[str, str] = {}
        for m in frag_metas:
            txt = self._fragment_user_text(m.session_id)
            if txt:
                frag_texts[m.session_id] = txt
        wanted = set(frag_texts.values())
        absorbed: set[str] = set()
        if wanted:
            real_paths = sorted(
                (p for p in self._iter_jsonl() if p.stem not in self._frag_ids),
                key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
                reverse=True,
            )
            scanned = 0
            for path in real_paths:
                if not wanted or scanned > _ABSORB_SCAN_CAP_BYTES:
                    break
                with contextlib.suppress(OSError):
                    scanned += path.stat().st_size
                for row in read_jsonl(path):
                    if row.get("type") != "user":
                        continue
                    role, text, _tools = self._row_content(row)
                    if role == "user" and text and text.strip() in wanted:
                        wanted.discard(text.strip())
                        if not wanted:
                            break
            found = set(frag_texts.values()) - wanted
            absorbed = {sid for sid, txt in frag_texts.items() if txt in found}
        if sig is not None:
            _QODER_ABSORB_CACHE[cache_key] = (sig, absorbed)
        return absorbed

    def load(self, session_id: str):
        """Load (+ merge grouped fragments) and re-apply the official title.

        The cockpit detail view rebuilds the bundle from load(), so the meta
        title must carry the same quest/wake overlay the list shows — otherwise
        the two views disagree about a session's name.
        """
        group = self._frag_groups.get(session_id)
        if group and len(group) > 1:
            paths: list[Path] = []
            for fid in group:
                paths.extend(self._resolve_group(fid))
            raw = self._load_paths(paths, session_id) if paths else None
        else:
            raw = super().load(session_id)
        if raw is None:
            return None
        official = self._load_quest_titles().get(session_id) or self._wake_titles().get(session_id)
        if official:
            raw.meta.title = official
        return raw

    def _wake_titles(self) -> dict[str, str]:
        """qs_* session titles from the QoderWake board projection (read-only)."""
        try:
            import sqlite3

            db = home() / self.wake_store / "data" / "store" / "qoderwake.sqlite"
            if not db.is_file():
                return {}
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT source_task_id, title FROM board_task_projection "
                    "WHERE title IS NOT NULL AND title != ''"
                ).fetchall()
            finally:
                conn.close()
            return {str(s): str(t) for s, t in rows if s and t}
        except Exception:
            return {}

    def _load_quest_titles(self) -> dict[str, str]:
        """Map executionSessionId -> title from the IDE global state DB."""
        if self._quest_titles is not None:
            return self._quest_titles
        titles: dict[str, str] = {}
        try:
            import sqlite3

            appdata = os.environ.get("APPDATA")
            if not appdata:
                self._quest_titles = titles
                return titles
            db = Path(appdata) / self.appdata_product / "User" / "globalStorage" / "state.vscdb"
            if not db.is_file():
                self._quest_titles = titles
                return titles
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT value FROM ItemTable WHERE key IN "
                    "('aicoding.questTaskListSnapshot', 'aicoding.questArchivedTaskList')"
                ).fetchall()
            finally:
                conn.close()
            for (blob,) in rows:
                if not blob:
                    continue
                try:
                    snap = json.loads(blob)
                except ValueError:
                    continue
                # snapshot: {folders:{path:{tasks:[...]}}}; archived list may be
                # {folders:...} too or a bare list of tasks.
                task_lists: list[list] = []
                if isinstance(snap, dict) and isinstance(snap.get("folders"), dict):
                    for fdata in snap["folders"].values():
                        if isinstance(fdata, dict) and isinstance(fdata.get("tasks"), list):
                            task_lists.append(fdata["tasks"])
                elif isinstance(snap, list):
                    task_lists.append(snap)
                for tasks in task_lists:
                    for task in tasks:
                        if not isinstance(task, dict):
                            continue
                        sid = task.get("executionSessionId") or task.get("designSessionId")
                        title = task.get("title") or task.get("name") or task.get("query")
                        # "Untitled" is the IDE's empty placeholder; it is worse
                        # than the transcript-derived title it would displace.
                        if str(title).strip().lower() in ("untitled", "无标题", ""):
                            continue
                        if sid and title:
                            titles[str(sid)] = str(title)
        except Exception:  # DB locked, schema drift, no sqlite — titles stay heuristic
            pass
        self._quest_titles = titles
        return titles


class QoderIdeParser(QodercnIdeParser):
    """Qoder IDE (international edition) — same layout under ~/.qoder.

    The international and CN builds are separate installs with separate stores
    (``.qoder`` vs ``.qoder-cn``) and separate state DBs (``%APPDATA%/Qoder``
    vs ``%APPDATA%/QoderCN``); everything else — dialect, quest titles, the
    qoderwake board overlay — behaves identically.
    """

    cli = "qoder-ide"
    projects_dirname = ".qoder"
    appdata_product = "Qoder"
    wake_store = ".qoderwake"

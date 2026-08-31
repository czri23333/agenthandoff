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

import json
import os
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
        """Cheap scan of the first lines to build a list entry."""
        rows = read_jsonl(path, limit=50)
        if not rows:
            return None
        cwd = ""
        session_id = path.stem
        title = ""
        started = updated = None
        for r in rows:
            cwd = cwd or (r.get("cwd") or "")
            session_id = r.get("sessionId") or session_id
            if r.get("type") == "summary" and r.get("summary"):
                title = title or str(r["summary"])
            role, text, _tools = self._row_content(r)
            if role == "user" and text and not self.is_noise(text):
                title = title or text[:80]
                started = _iso(r.get("timestamp")) or started
                break
        updated = _record_stamp(rows) or _record_stamp(_tail_rows(path))
        if updated is None:
            # Only a store that records no timestamps at all may be dated by its
            # filesystem - and then the date means "copied", not "last turn".
            try:
                updated = _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
            except OSError:
                updated = None
        return SessionMeta(
            cli=self.cli,
            session_id=session_id,
            title=title or session_id,
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

    def _resolve_group(self, session_id: str) -> list[Path]:
        """All files that make up one session; cheap and storage-layout agnostic."""
        if session_id.endswith(".jsonl"):  # a caller passed a path
            one = Path(session_id)
            return [one] if one.exists() else []
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

    def _tool_name_input(self, block: dict) -> tuple[str, dict]:
        name = block.get("name") or block.get("tool") or block.get("toolName") or "tool"
        tool_input = block.get("input")
        if not isinstance(tool_input, dict):
            inner = block.get("state") or {}
            tool_input = inner.get("input") if isinstance(inner, dict) else {}
        return str(name), (tool_input if isinstance(tool_input, dict) else {})

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
                    messages.append(Message(role=role, text=text, at=at))

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


class ClaudeCodeParser(JsonlSessionParser):
    cli = "claude"
    projects_dirname = ".claude"


class CodebuddyParser(JsonlSessionParser):
    cli = "codebuddy"
    projects_dirname = ".codebuddy"


class CodebuddyCnParser(JsonlSessionParser):
    """CodeBuddy CN edition — same layout under ~/.codebuddycn."""

    cli = "codebuddy-cn"
    projects_dirname = ".codebuddycn"


class QoderworkParser(JsonlSessionParser):
    """Qoderwork — Claude-Code-style JSONL under ~/.qoderwork/projects."""

    cli = "qoderwork"
    projects_dirname = ".qoderwork"


class QoderworkCnParser(JsonlSessionParser):
    """Qoderwork CN — a separate login (second account) under ~/.qoderworkcn.

    Variant directories of the same product are distinct account scopes:
    the user may run one account per variant (verified live: each carries
    its own .auth/machine_id). ``origin`` records which store a session
    came from so multi-account usage stays distinguishable.
    """

    cli = "qoderwork-cn"
    projects_dirname = ".qoderworkcn"


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
    """

    cli = "qodercn-ide"
    projects_dirname = ".qoder-cn"

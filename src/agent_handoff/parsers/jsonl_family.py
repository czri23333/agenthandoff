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

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta, TodoItem, ts_to_iso
from agent_handoff.parsers.base import Parser, as_text_blocks, read_jsonl


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

    def available(self) -> bool:
        return self.root.is_dir()

    # -- discovery ----------------------------------------------------------

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        metas: list[SessionMeta] = []
        for f in self.root.rglob("*.jsonl"):
            meta = self._peek(f)
            if meta:
                metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def _origin(self) -> str | None:
        """Store directory (e.g. .qoderwork vs .qoderworkcn) = account scope."""
        name = self.root.parent.name
        return name if name.startswith(".") else None

    def _peek(self, path: Path) -> SessionMeta | None:
        """Cheap scan of the first/last lines to build a list entry."""
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
        path = self._resolve(session_id)
        if path is None:
            return None
        return self._load_file(path)

    def _resolve(self, session_id: str) -> Path | None:
        """Accept a bare session id or a path; rglob keeps it storage-agnostic."""
        if session_id.endswith(".jsonl"):
            p = Path(session_id)
            return p if p.exists() else None
        hits = list(self.root.rglob(f"{session_id}.jsonl"))
        return hits[0] if hits else None

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

    def _load_file(self, path: Path) -> RawSession:
        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        todos: list[TodoItem] = []
        cwd = ""
        session_id = path.stem
        title = ""
        started = None

        for row in read_jsonl(path):
            if row.get("type") == "summary":
                continue
            cwd = cwd or (row.get("cwd") or "")
            session_id = row.get("sessionId") or session_id
            at = _iso(row.get("timestamp"))
            started = started or at

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
                if role == "user" and not title:
                    title = text[:80]
                messages.append(Message(role=role, text=text, at=at))

        meta = SessionMeta(
            cli=self.cli,
            session_id=session_id,
            title=title or session_id,
            cwd=cwd,
            started_at=started,
            updated_at=_iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)),
            source_path=str(path),
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

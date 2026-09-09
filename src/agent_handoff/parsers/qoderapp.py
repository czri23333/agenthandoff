"""QoderWork desktop-app parser — Task-session SQLite store.

Layout (verified live, 2026-09-03, three product variants):
    %APPDATA%/QoderWork/data/agents.db        (international)
    %APPDATA%/QoderWork CN/data/agents.db     (CN, second account)
    %APPDATA%/QwenWorkCN/data/agents.db       (Qwen edition)
        chats        id / name / project_id / created_at / updated_at /
                     chat_type / source_chat_id / deleted_at
        messages     chat_id / sequence / role / parts (JSON) /
                     metadata (JSON, carries the CLI sessionId) /
                     searchable_text / created_at
        projects     id / name (workspace display name -> cwd-ish domain)

Parts dialect: {"type":"text","text":...} dialogue,
{"type":"tool-<Name>","toolName":...,"input":{...}} tool calls,
{"type":"error",...} provider errors. Thinking blocks are tool-Thinking
with input.text — surfaced as [思考] turns, the same convention as the
CherryStudio parser.

These Task chats are the desktop face of the same work the qoderwork CLI
records as JSONL (metadata.sessionId links the two); both stay listed so
each surface keeps its own provenance. Read-only URI mode throughout.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta, ts_to_iso
from agent_handoff.parsers.base import Parser


def _appdata() -> Path:
    import os

    base = os.environ.get("APPDATA")
    if base:
        return Path(base)
    return home() / "AppData" / "Roaming"


def _epoch(value) -> int | None:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    # epoch seconds (10 digits) vs millis (13 digits)
    return v * 1000 if v < 10_000_000_000 else v


class _QoderAppSharedMixin:
    app_dirname: str = "QoderWork"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _appdata() / self.app_dirname / "data" / "agents.db"

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        return con

    def available(self) -> bool:
        return self.db_path.exists()

    def _projects(self, con: sqlite3.Connection) -> dict[str, str]:
        try:
            return {r["id"]: r["name"] or "" for r in con.execute("SELECT id, name FROM projects")}
        except sqlite3.Error:
            return {}

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        out: list[SessionMeta] = []
        try:
            with self._connect() as con:
                names = self._projects(con)
                rows = con.execute(
                    "SELECT c.id, c.name, c.project_id, c.created_at, c.updated_at, "
                    "c.chat_type, COUNT(m.id) AS n "
                    "FROM chats c LEFT JOIN messages m ON m.chat_id=c.id "
                    "WHERE c.deleted_at IS NULL GROUP BY c.id ORDER BY c.updated_at DESC"
                ).fetchall()
        except sqlite3.Error:
            return []
        for r in rows:
            notes = [f"chat_type:{r['chat_type']}"] if r["chat_type"] else []
            if not (r["n"] or 0):
                notes.append("empty:no_message_rows")
            out.append(
                SessionMeta(
                    cli=self.cli,  # type: ignore[attr-defined]
                    session_id=r["id"],
                    title=r["name"] or r["id"],
                    cwd=names.get(r["project_id"] or "") or "",
                    started_at=ts_to_iso(_epoch(r["created_at"])),
                    updated_at=ts_to_iso(_epoch(r["updated_at"])),
                    source_path=str(self.db_path),
                    notes=notes,
                )
            )
        return out

    def raw_archive(self, session_id: str) -> list[dict] | None:
        if not self.available():
            return None
        from agent_handoff.parsers.base import json_records_entry

        records: list[tuple[str, dict]] = []
        try:
            with self._connect() as con:
                chat = con.execute("SELECT * FROM chats WHERE id=?", (session_id,)).fetchone()
                if chat is None:
                    return None
                records.append(("chats", dict(chat)))
                for row in con.execute(
                    "SELECT * FROM messages WHERE chat_id=? ORDER BY sequence", (session_id,)
                ):
                    records.append(("messages", dict(row)))
        except sqlite3.Error:
            return None
        if not records:
            return None
        return [json_records_entry(f"qoderapp/{session_id}.records.jsonl", records)]

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        with self._connect() as con:
            try:
                chat = con.execute("SELECT * FROM chats WHERE id=?", (session_id,)).fetchone()
                if chat is None:
                    return None
                names = self._projects(con)
                rows = con.execute(
                    "SELECT role, parts, metadata, searchable_text, created_at "
                    "FROM messages WHERE chat_id=? ORDER BY sequence",
                    (session_id,),
                ).fetchall()
                try:
                    subs = con.execute(
                        "SELECT model_level, ext FROM sub_chats WHERE chat_id=?",
                        (session_id,),
                    ).fetchall()
                except sqlite3.Error:
                    subs = []
            except sqlite3.Error:
                return None

        # Conversation-level billing the store does keep: sub_chats.model_level
        # (e.g. qmodel_preview) plus the context-usage snapshot in ext.
        # No per-message usage exists — every turn inherits the chat model,
        # tokens stay empty (honest absence, not a parse miss).
        chat_model: str | None = None
        quota_note: str | None = None
        for sub in subs:
            try:
                level = sub["model_level"]
            except (KeyError, IndexError, TypeError):
                level = None
            if not chat_model and isinstance(level, str) and level:
                chat_model = level
            try:
                snap = (json.loads(sub["ext"] or "{}") or {}).get("contextUsageSnapshot") or {}
            except ValueError:
                snap = {}
            if isinstance(snap, dict) and snap.get("percentage") is not None and quota_note is None:
                quota_note = (
                    f"context_fill:{float(snap.get('percentage', 0)):.1%}"
                    f"@{snap.get('model') or chat_model or '?'}"
                )

        meta = SessionMeta(
            cli=self.cli,  # type: ignore[attr-defined]
            session_id=session_id,
            title=chat["name"] or session_id,
            cwd=names.get(chat["project_id"] or "") or "",
            started_at=ts_to_iso(_epoch(chat["created_at"])),
            updated_at=ts_to_iso(_epoch(chat["updated_at"])),
            source_path=str(self.db_path),
            model=chat_model,
        )
        # The store records no model or usage: Message.model/tokens stay
        # empty (honest absence). messages[].metadata.sessionId links the
        # desktop Task chat to the CLI JSONL session of the same work —
        # surfaced as a note so the cockpit can cross-link the two faces.
        linked: list[str] = []
        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        for row in rows:
            role = row["role"] or ""
            if role not in ("user", "assistant"):
                continue
            try:
                meta_json = json.loads(row["metadata"] or "{}")
            except ValueError:
                meta_json = {}
            link = meta_json.get("sessionId")
            if isinstance(link, str) and link and link not in linked:
                linked.append(link)
            at = ts_to_iso(_epoch(row["created_at"]))
            # Measured cost proxy: the store's own per-message duration.
            row_dur = meta_json.get("durationMs")
            row_dur = row_dur if isinstance(row_dur, int) and row_dur > 0 else None
            try:
                parts = json.loads(row["parts"] or "[]")
            except ValueError:
                parts = []
            if not isinstance(parts, list):
                parts = []
            if not parts and row["searchable_text"]:
                praw = row["searchable_text"]
                text = self.clean_text(praw)
                if text and not self.is_noise(text):
                    messages.append(
                        self.msg(role, praw, text=text, at=at, model=chat_model, dur_ms=row_dur)
                    )
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                ptype = str(part.get("type") or "")
                if ptype == "text":
                    praw = str(part.get("text") or "")
                    text = self.clean_text(praw)
                    if text and not self.is_noise(text):
                        messages.append(
                            self.msg(role, praw, text=text, at=at, model=chat_model, dur_ms=row_dur)
                        )
                elif ptype.startswith("tool-"):
                    name = str(part.get("toolName") or ptype[5:] or "tool")
                    if name == "Thinking":
                        praw = str((part.get("input") or {}).get("text") or "")
                        text = self.clean_text(praw)
                        if text and not self.is_noise(text):
                            messages.append(
                            self.msg(
                                "assistant",
                                f"[思考] {praw}",
                                text=f"[思考] {text}",
                                at=at,
                                model=chat_model,
                                dur_ms=row_dur,
                            )
                        )
                    else:
                        tools[name] += 1
                        for p in self.extract_paths(part.get("input") or {}):
                            files[p] += 1
                elif ptype == "error":
                    praw = str(part.get("text") or "")
                    text = self.clean_text(praw)
                    if text:
                        messages.append(
                            self.msg(
                                "assistant",
                                f"[工具error] {praw}",
                                text=f"[工具error] {text[:500]}",
                                at=at,
                                model=chat_model,
                                dur_ms=row_dur,
                            )
                        )
        if linked:
            meta.notes = [*meta.notes, f"linked_cli_sessions:{','.join(linked[:8])}"]
        if quota_note:
            meta.notes = [*meta.notes, quota_note]
        return self.build_raw(meta, messages, [], files, tools)


class QoderworkAppParser(_QoderAppSharedMixin, Parser):
    """QoderWork desktop app Task chats (international edition)."""

    cli = "qoderwork-app"
    app_dirname = "QoderWork"


class QoderworkCnAppParser(_QoderAppSharedMixin, Parser):
    """QoderWork CN desktop app Task chats (separate login)."""

    cli = "qoderwork-cn-app"
    app_dirname = "QoderWork CN"


class QwenworkAppParser(_QoderAppSharedMixin, Parser):
    """QwenWork CN desktop app Task chats."""

    cli = "qwenwork-app"
    app_dirname = "QwenWorkCN"

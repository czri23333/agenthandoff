"""ZCode parser — reads the local SQLite session store (~/.zcode/cli/db/db.sqlite).

Opened in read-only URI mode so a running ZCode instance is never disturbed;
WAL sidecar files are only read, never written.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from agent_handoff.model import (
    Interruption,
    Message,
    RawSession,
    SessionMeta,
    TodoItem,
    ts_to_iso,
)
from agent_handoff.parsers.base import Parser


class ZcodeParser(Parser):
    cli = "zcode"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        return con

    def available(self) -> bool:
        return self.db_path.exists()

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        out: list[SessionMeta] = []
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, title, directory, time_created, time_updated "
                "FROM session ORDER BY time_updated DESC"
            ).fetchall()
        for r in rows:
            out.append(
                SessionMeta(
                    cli=self.cli,
                    session_id=r["id"],
                    title=r["title"] or r["id"],
                    cwd=r["directory"] or "",
                    started_at=ts_to_iso(r["time_created"]),
                    updated_at=ts_to_iso(r["time_updated"]),
                    source_path=str(self.db_path),
                )
            )
        return out

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        with self._connect() as con:
            sess = con.execute(
                "SELECT id, title, directory, time_created, time_updated, parent_id "
                "FROM session WHERE id=?",
                (session_id,),
            ).fetchone()
            if sess is None:
                return None

            messages: list[Message] = []
            files: Counter[str] = Counter()
            tools: Counter[str] = Counter()
            model: str | None = None
            tokens_in = tokens_out = 0

            msg_rows = con.execute(
                "SELECT id, data, time_created FROM message WHERE session_id=? ORDER BY sequence",
                (session_id,),
            ).fetchall()
            for m in msg_rows:
                try:
                    mdata = json.loads(m["data"])
                except (json.JSONDecodeError, TypeError):
                    mdata = {}
                role = mdata.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                parts = con.execute(
                    "SELECT data FROM part WHERE message_id=? ORDER BY sequence",
                    (m["id"],),
                ).fetchall()
                texts: list[str] = []
                for p in parts:
                    try:
                        pdata = json.loads(p["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    ptype = pdata.get("type")
                    if ptype == "text":
                        t = self.clean_text(pdata.get("text") or "")
                        if t and not self.is_noise(t):
                            texts.append(t)
                    elif ptype == "tool":
                        tool_name = pdata.get("tool") or "tool"
                        tools[tool_name] += 1
                        state = pdata.get("state") or {}
                        tool_input = state.get("input") or {}
                        if isinstance(tool_input, dict):
                            for path in self.extract_paths(tool_input):
                                files[path] += 1

                if role == "assistant" and mdata.get("modelID"):
                    model = mdata["modelID"]
                tok = mdata.get("tokens")
                if isinstance(tok, dict):
                    tokens_in += int(tok.get("input") or tok.get("inputTokens") or 0)
                    tokens_out += int(tok.get("output") or tok.get("outputTokens") or 0)

                if texts:
                    messages.append(
                        Message(role=role, text="\n".join(texts), at=ts_to_iso(m["time_created"]))
                    )

            todos = [
                TodoItem(
                    content=r["content"],
                    status=r["status"] or "pending",
                    priority=r["priority"] or "",
                )
                for r in con.execute(
                    "SELECT content, status, priority FROM todo "
                    "WHERE session_id=? ORDER BY position",
                    (session_id,),
                ).fetchall()
            ]

        interruption = self._interruption(con, session_id)
        try:
            provider_row = con.execute(
                "SELECT provider_id FROM model_usage WHERE session_id=? "
                "ORDER BY started_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        except sqlite3.Error:
            provider_row = None

        meta = SessionMeta(
            cli=self.cli,
            session_id=sess["id"],
            title=sess["title"] or sess["id"],
            cwd=sess["directory"] or "",
            started_at=ts_to_iso(sess["time_created"]),
            updated_at=ts_to_iso(sess["time_updated"]),
            model=model,
            tokens_in=tokens_in or None,
            tokens_out=tokens_out or None,
            source_path=str(self.db_path),
            provider=provider_row[0] if provider_row else None,
            parent_session_id=sess["parent_id"],
        )
        return self.build_raw(meta, messages, todos, files, tools, interruption)

    def peek_status(self, session_id: str) -> str | None:
        """One SQL against turn_usage — cheap enough for list views."""
        if not self.available():
            return None
        try:
            with self._connect() as con:
                row = con.execute(
                    "SELECT context_exceeded, cancelled_by_user, error_type "
                    "FROM turn_usage WHERE session_id=? ORDER BY started_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
            if row is None:
                return None
            exceeded, cancelled, error_type = row
            if cancelled:
                return "cancelled"
            if exceeded:
                return "context_exceeded"
            if error_type:
                return "error"
            return "clean"
        except sqlite3.Error:
            return None

    @staticmethod
    def _interruption(con: sqlite3.Connection, session_id: str) -> Interruption:
        """Read how the session actually ended from usage stats.

        The store records cancellations, context-window deaths and model
        errors explicitly; the newest turn decides. A token-limit cut-off
        (finish_reason='length') on the newest model call also counts.
        """
        try:
            turn = con.execute(
                "SELECT status, context_exceeded, cancelled_by_user, error_type "
                "FROM turn_usage WHERE session_id=? ORDER BY started_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if turn is not None:
                status, exceeded, cancelled, error_type = turn
                if cancelled:
                    return Interruption(kind="cancelled", detail=f"last turn status={status}")
                if exceeded:
                    return Interruption(kind="context_exceeded")
                if error_type:
                    return Interruption(kind="error", detail=f"error_type={error_type}")
            finish = con.execute(
                "SELECT finish_reason FROM model_usage WHERE session_id=? "
                "ORDER BY started_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if finish is not None and finish[0] == "length":
                return Interruption(kind="length_truncated")
        except sqlite3.Error:
            # Usage tables may not exist in older stores — absence of evidence
            # is not evidence of a clean end; summarize adds its own inference.
            pass
        return Interruption()

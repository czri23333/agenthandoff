"""CherryStudio parser — desktop AI-workbench SQLite store.

Layout (verified live, 2026-09-03):
    %APPDATA%/CherryStudio/Data/agents.db
        agents               agent defs (id -> display name, e.g. Cherry Claw)
        sessions             id / name / agent_id / created_at / updated_at
        session_messages     session_id / role / content (JSON) / created_at
            content = {"message": {role/model/usage/...}, "blocks": [
                main_text | thinking | tool | unknown ...]}

Sessions are real user↔assistant dialogues (model/provider/usage recorded
per turn, tool calls embedded as blocks), so they parse as first-class
sessions — same as the zcode/opencode SQLite family. Read-only URI mode so
a running CherryStudio instance is never disturbed.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta
from agent_handoff.parsers.base import Parser


def _appdata() -> Path:
    import os

    base = os.environ.get("APPDATA")
    if base:
        return Path(base)
    return home() / "AppData" / "Roaming"


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class CherryStudioParser(Parser):
    cli = "cherrystudio"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _appdata() / "CherryStudio" / "Data" / "agents.db"

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
        try:
            with self._connect() as con:
                names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM agents")}
                rows = con.execute(
                    "SELECT s.id, s.name, s.agent_id, s.created_at, s.updated_at, "
                    "COUNT(m.id) AS n "
                    "FROM sessions s LEFT JOIN session_messages m "
                    "ON m.session_id=s.id GROUP BY s.id "
                    "ORDER BY s.updated_at DESC"
                ).fetchall()
        except sqlite3.Error:
            return []
        for r in rows:
            agent = names.get(r["agent_id"] or "") or None
            notes = [f"agent:{agent}"] if agent else []
            if not (r["n"] or 0):
                notes.append("empty:no_message_rows")
            out.append(
                SessionMeta(
                    cli=self.cli,
                    session_id=r["id"],
                    title=r["name"] or r["id"],
                    cwd="",
                    started_at=r["created_at"] or None,
                    updated_at=r["updated_at"] or None,
                    source_path=str(self.db_path),
                    provider=agent,
                    notes=notes,
                )
            )
        return out

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """Every row the store holds for this session — all columns of
        sessions/session_messages (+ the agent row), verbatim."""
        if not self.available():
            return None
        from agent_handoff.parsers.base import json_records_entry

        records: list[tuple[str, dict]] = []
        try:
            with self._connect() as con:
                sess = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
                if sess is None:
                    return None
                records.append(("sessions", dict(sess)))
                agent_id = sess["agent_id"]
                if agent_id:
                    for row in con.execute("SELECT * FROM agents WHERE id=?", (agent_id,)):
                        records.append(("agents", dict(row)))
                for row in con.execute(
                    "SELECT * FROM session_messages WHERE session_id=? ORDER BY created_at",
                    (session_id,),
                ):
                    records.append(("session_messages", dict(row)))
        except sqlite3.Error:
            return None
        if not records:
            return None
        return [json_records_entry(f"cherrystudio/{session_id}.records.jsonl", records)]

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        with self._connect() as con:
            try:
                sess = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
                if sess is None:
                    return None
                agent = con.execute("SELECT name FROM agents WHERE id=?", (sess["agent_id"],)).fetchone()
                rows = con.execute(
                    "SELECT role, content, created_at FROM session_messages "
                    "WHERE session_id=? ORDER BY created_at",
                    (session_id,),
                ).fetchall()
            except sqlite3.Error:
                return None

        agent_name = agent["name"] if agent else None
        meta = SessionMeta(
            cli=self.cli,
            session_id=session_id,
            title=sess["name"] or session_id,
            cwd="",
            started_at=sess["created_at"] or None,
            updated_at=sess["updated_at"] or None,
            source_path=str(self.db_path),
            provider=agent_name,
        )

        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        for row in rows:
            try:
                payload = json.loads(row["content"] or "{}")
            except ValueError:
                continue
            msg = payload.get("message") if isinstance(payload, dict) else None
            msg = msg if isinstance(msg, dict) else {}
            role = str(msg.get("role") or row["role"] or "")
            if role not in ("user", "assistant"):
                continue
            model = msg.get("model")
            model_name = model.get("name") if isinstance(model, dict) else None
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            at = msg.get("createdAt") or row["created_at"]
            for block in payload.get("blocks") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    praw = _text(block.get("content"))
                    text = self.clean_text(praw)
                    if text and not self.is_noise(text):
                        messages.append(
                            self.msg("assistant", f"[思考] {praw}", text=f"[思考] {text}", at=at,
                                     model=model_name or None)
                        )
                elif btype == "main_text":
                    praw = _text(block.get("content"))
                    text = self.clean_text(praw)
                    if text and not self.is_noise(text):
                        messages.append(
                            self.msg(
                                role, praw, text=text, at=at, model=model_name or None,
                                tokens_in=usage.get("prompt_tokens"),
                                tokens_out=usage.get("completion_tokens"),
                            )
                        )
                elif btype == "tool":
                    tools["tool"] += 1
                    for p in self.extract_paths(block.get("metadata") or {}):
                        files[p] += 1
                    praw = _text(block.get("content"))[:500]
                    text = self.clean_text(praw)
                    if text and not self.is_noise(text):
                        messages.append(self.msg("assistant", f"[工具] {praw}",
                                                 text=f"[工具] {text}", at=at,
                                                 model=model_name or None))
        return self.build_raw(meta, messages, [], files, tools)

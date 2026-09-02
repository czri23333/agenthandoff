"""QoderWake parser — the digital-employee daemon's SQLite store.

Layout (verified live, 2026-09-01):
    ~/.qoderwake-cn/data/store/qoderwake.sqlite
        team_group_conversations_v3   team chats: task_name is the real title
        team_group_messages_v3        payload_json.body carries the dialogue
        board_task_projection         source_task_id -> title (also enriches the
                                      qs_* sessions that surface in .qoder-cn)

Team-group conversations are real sessions the user addresses in the QoderWake
console; their transcripts never reach ~/.qoder-cn/projects, so this parser is
the only way they become visible. Worker sessions spawned *by* a group do land
in ~/.qoder-cn under the group workspace and are handled by QodercnIdeParser.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta
from agent_handoff.parsers.base import Parser

# sender_type -> conversation role
_ROLE = {"user": "user", "member": "assistant"}


def _norm_ts(value) -> str | None:
    """qoderwake stores +08:00 offset timestamps; normalize to local ISO."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone().isoformat(timespec="seconds")
    except ValueError:
        return None


class QoderwakeParser(Parser):
    """QoderWake (international edition) — daemon store under ~/.qoderwake."""

    cli = "qoderwake"
    store_dirname = ".qoderwake"

    def __init__(self, root=None) -> None:
        self.root = Path(root) if root else home() / self.store_dirname / "data" / "store"

    def available(self) -> bool:
        return self._db().is_file()

    def _db(self) -> Path:
        return Path(self.root) / "qoderwake.sqlite"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db()}?mode=ro", uri=True)

    # -- discovery ----------------------------------------------------------

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT id, group_id, task_name, workspace_root, model_id, "
                    "created_at, last_message_at "
                    "FROM team_group_conversations_v3"
                ).fetchall()
        except sqlite3.Error:
            return []
        metas: list[SessionMeta] = []
        for cid, group_id, task_name, ws_root, model_id, created, last_msg in rows:
            metas.append(
                SessionMeta(
                    cli=self.cli,
                    session_id=str(cid),
                    title=str(task_name) if task_name else str(cid),
                    cwd=str(ws_root or ""),
                    started_at=_norm_ts(created),
                    updated_at=_norm_ts(last_msg) or _norm_ts(created),
                    source_path=str(self._db()),
                    model=str(model_id) if model_id else None,
                    notes=([f"team: {group_id}"] if group_id else []),
                )
            )
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    # -- loading ------------------------------------------------------------

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        try:
            with self._connect() as con:
                crow = con.execute(
                    "SELECT id, group_id, task_name, workspace_root, model_id, created_at "
                    "FROM team_group_conversations_v3 WHERE id=?",
                    (session_id,),
                ).fetchone()
                if crow is None:
                    return None
                cid, group_id, task_name, ws_root, model_id, created = crow
                mrows = con.execute(
                    "SELECT sender_type, kind, payload_json, created_at "
                    "FROM team_group_messages_v3 WHERE session_id=? ORDER BY created_at",
                    (session_id,),
                ).fetchall()
        except sqlite3.Error:
            return None

        meta = SessionMeta(
            cli=self.cli,
            session_id=str(cid),
            title=str(task_name) if task_name else str(cid),
            cwd=str(ws_root or ""),
            started_at=_norm_ts(created),
            source_path=str(self._db()),
            model=str(model_id) if model_id else None,
            notes=([f"team: {group_id}"] if group_id else []),
        )

        messages: list[Message] = []
        for sender_type, _kind, pj, created_at in mrows:
            role = _ROLE.get(str(sender_type))
            if role is None:
                continue
            try:
                p = json.loads(pj) if pj else {}
            except (ValueError, TypeError):
                continue
            body = p.get("body")
            text = body.get("text") if isinstance(body, dict) else body
            text = self.clean_text(str(text or ""))
            if not text or self.is_noise(text):
                continue
            messages.append(Message(role=role, text=text, at=_norm_ts(created_at)))

        return self.build_raw(meta, messages, [], Counter(), Counter())


class QoderwakeCnParser(QoderwakeParser):
    """QoderWake CN edition — same schema under ~/.qoderwake-cn.

    International and CN daemons are separate installs; the sqlite schema
    (team_group_conversations_v3 / team_group_messages_v3 /
    board_task_projection) is identical in both.
    """

    cli = "qoderwake-cn"
    store_dirname = ".qoderwake-cn"

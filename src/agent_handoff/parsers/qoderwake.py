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
from agent_handoff.parsers.base import Parser, db_version, probe_memo
from agent_handoff.parsers.jsonl_family import QodercnIdeParser, _family_of_path

# sender_type -> conversation role
_ROLE = {"user": "user", "member": "assistant"}


def _body_text(payload_json) -> str:
    """The text a team-chat message carries, exactly as the page reads it.

    `load()` and the needs-input probe ask the same question of the same rows, so
    the extraction lives in one function: a probe that re-derives its renderer's
    predicate is a probe that can drift from the page it must agree with (Round
    58's lesson, applied before it had to be learned twice).
    """
    try:
        p = json.loads(payload_json) if payload_json else {}
    except (ValueError, TypeError):
        return ""
    body = p.get("body") if isinstance(p, dict) else None
    btext = body.get("text") if isinstance(body, dict) else body
    return str(btext or "")


def _carries_turn(parser: Parser, sender_type, payload_json) -> tuple[str, str] | None:
    """The role and text of a message that reaches the transcript, else None.

    A message counts when its sender maps to a role and its body carries text
    that survives cleaning and is not an injected reminder — the page drops the
    rest, and so must anything that claims to read the page's last word.
    """
    role = _ROLE.get(str(sender_type))
    if role is None:
        return None
    text = parser.clean_text(_body_text(payload_json))
    if not text or parser.is_noise(text):
        return None
    return role, text


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
    """QoderWake (international edition) — daemon store under ~/.qoderwake.

    Two sources, one family:
    * the daemon SQLite holds the team-group chats (console conversations);
    * worker/group transcripts land in the shared qoder store
      (~/.qoder/projects/<...wake...-workspace>), scanned below and titled
      by the board projection.
    """

    cli = "qoderwake"
    store_dirname = ".qoderwake"
    shared_store = ".qoder"

    def __init__(self, root=None) -> None:
        self.root = Path(root) if root else home() / self.store_dirname / "data" / "store"
        self._shared = self._shared_parser()
        # Per-pass state for the needs-input probe: the store version the
        # answers were read at, and which session ids are this daemon's own team
        # chats (as opposed to wake transcripts in the shared qoder store).
        self._probe_version: tuple | None = None
        self._team_ids: set[str] | None = None

    def _shared_parser(self):
        """The wake-family transcripts inside the shared qoder store."""
        try:
            shared = self.root.parent.parent.parent / self.shared_store / "projects"
        except (ValueError, OSError):
            return None
        if not shared.is_dir():
            return None
        return _WakeShared(shared, self.cli, self._appdata_product(), self._wake_store_dir())

    def _appdata_product(self) -> str:
        return "Qoder" if self.shared_store == ".qoder" else "QoderCN"

    def _wake_store_dir(self) -> str:
        return ".qoderwake" if self.shared_store == ".qoder" else ".qoderwake-cn"

    def _family_transcripts(self) -> list[SessionMeta]:
        if self._shared is None:
            return []
        return self._shared.list_sessions()

    # Message rows the team-chat probe reads, newest first. A message whose body
    # is empty or purely injected carries no turn, so the probe walks back to the
    # one that does — the same rule the detail page applies when it drops rows.
    _PROBE_ROWS = 50

    def peek_needs_reply(self, session_id: str) -> bool | None:
        """Ask whichever store holds this conversation's messages.

        Half of this entry's rows are wake transcripts in the shared qoder store,
        and the listing reaches them through `_shared` — which is the parser that
        owns the file index, the fragment merge and the tail probe. Without the
        delegation this entry answered "unknown" for every one of its own rows
        while its sibling parser was reading the very file (spec Round 56).

        The other half are the daemon's team-group chats: their messages live in
        this SQLite store (`team_group_messages_v3`), and until spec Round 59 this
        probe had no answer for them at all — measured on this machine, the two
        conversations it holds both end on an unanswered user turn, so the column
        was silent about exactly the rows its own detail page could answer. Round
        58's `probe_memo` carries them now: one bounded query per conversation per
        store change, and the answer is the newest message that reaches the page,
        which is what `load()` renders and nothing else.

        A team chat is identified by the conversation table, not by how its id
        looks: the set is read once per pass, because the alternative is a
        existence-check query on every row of the listing.
        """
        if self._team_ids is None:
            self._team_ids = self._read_team_ids()
        if session_id not in self._team_ids:
            return None if self._shared is None else self._shared.peek_needs_reply(session_id)
        if self._probe_version is None:
            self._probe_version = db_version(self._db())
        return probe_memo(
            str(self._db()), session_id, self._probe_version, lambda: self._team_needs(session_id)
        )

    def _read_team_ids(self) -> set[str]:
        """The conversation ids this daemon owns, or nothing if it cannot be read."""
        if not self.available():
            return set()
        try:
            with self._connect() as con:
                rows = con.execute("SELECT id FROM team_group_conversations_v3").fetchall()
            return {str(r[0]) for r in rows}
        except sqlite3.Error:
            return set()

    def _team_needs(self, session_id: str) -> bool | None:
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT sender_type, payload_json FROM team_group_messages_v3"
                    " WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (session_id, self._PROBE_ROWS),
                ).fetchall()
        except sqlite3.Error:
            return None
        for sender_type, pj in rows:
            turn = _carries_turn(self, sender_type, pj)
            if turn is not None:
                return turn[0] == "user"
        return None

    def hidden_sessions(self) -> list[SessionMeta]:
        """The wake transcripts the shared store dropped, which this entry owns.

        The listing and the hiding both happen on the shared parser (it reads
        that store), so the receipt has to be read from there too.
        """
        return [] if self._shared is None else self._shared.hidden_sessions()

    def available(self) -> bool:
        return self._db().is_file()

    def _db(self) -> Path:
        return Path(self.root) / "qoderwake.sqlite"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db()}?mode=ro", uri=True)

    # -- discovery ----------------------------------------------------------

    def list_sessions(self) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        if self.available():
            try:
                with self._connect() as con:
                    rows = con.execute(
                        "SELECT id, group_id, task_name, workspace_root, model_id, "
                        "created_at, last_message_at "
                        "FROM team_group_conversations_v3"
                    ).fetchall()
            except sqlite3.Error:
                rows = []
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
        known = {m.session_id for m in metas}
        for m in self._family_transcripts():
            if m.session_id not in known:
                metas.append(m)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    # -- loading ------------------------------------------------------------

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """Team chats record-level (all columns of the v3 tables); worker/
        group transcripts delegate to the shared-store archive."""
        if not self.available():
            return self._shared.raw_archive(session_id) if self._shared else None
        from agent_handoff.parsers.base import json_records_entry

        records: list[tuple[str, dict]] = []
        try:
            with self._connect() as con:
                for table in (
                    "team_group_conversations_v3",
                    "team_group_messages_v3",
                    "team_group_activities_v3",
                ):
                    idcol = "id" if table == "team_group_conversations_v3" else "session_id"
                    try:
                        cur = con.execute(
                            f"SELECT * FROM {table} WHERE {idcol}=?", (session_id,)
                        )
                        cols = [d[0] for d in cur.description]
                        for row in cur.fetchall():
                            records.append((table, dict(zip(cols, row, strict=True))))
                    except sqlite3.Error:
                        continue
        except sqlite3.Error:
            return None
        if records:
            return [json_records_entry(f"qoderwake/{session_id}.records.jsonl", records)]
        return self._shared.raw_archive(session_id) if self._shared else None

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return self._shared.load(session_id) if self._shared else None
        try:
            with self._connect() as con:
                crow = con.execute(
                    "SELECT id, group_id, task_name, workspace_root, model_id, created_at "
                    "FROM team_group_conversations_v3 WHERE id=?",
                    (session_id,),
                ).fetchone()
                if crow is None:
                    return self._shared.load(session_id) if self._shared else None
                cid, group_id, task_name, ws_root, model_id, created = crow
                mrows = con.execute(
                    "SELECT sender_type, kind, payload_json, created_at "
                    "FROM team_group_messages_v3 WHERE session_id=? ORDER BY created_at",
                    (session_id,),
                ).fetchall()
        except sqlite3.Error:
            return self._shared.load(session_id) if self._shared else None

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

        # The store records the model per conversation, not per message or
        # with usage: every turn inherits the conversation model, tokens stay
        # empty (honest absence, not a parse miss).
        convo_model = str(model_id) if model_id else None

        messages: list[Message] = []
        for sender_type, _kind, pj, created_at in mrows:
            turn = _carries_turn(self, sender_type, pj)
            if turn is None:
                continue
            role, text = turn
            messages.append(
                self.msg(
                    role,
                    _body_text(pj),
                    text=text,
                    at=_norm_ts(created_at),
                    model=convo_model,
                )
            )

        return self.build_raw(meta, messages, [], Counter(), Counter())


class QoderwakeCnParser(QoderwakeParser):
    """QoderWake CN edition — same schema under ~/.qoderwake-cn.

    International and CN daemons are separate installs; the sqlite schema
    (team_group_conversations_v3 / team_group_messages_v3 /
    board_task_projection) is identical in both.
    """

    cli = "qoderwake-cn"
    store_dirname = ".qoderwake-cn"
    shared_store = ".qoder-cn"


class _WakeShared(QodercnIdeParser):
    """Wake-family transcripts inside the shared qoder store.

    The group/worker workspace dirs are marked ``qoderwake`` in their name;
    everything else in the store is the IDE's (or work's) business. The IDE
    parser pipeline already merges fragments, absorbs duplicates and applies
    the board titles — filter the other direction and call it the wake list.
    """

    def __init__(
        self, shared_root: Path, cli: str, appdata_product: str, wake_store: str
    ) -> None:
        super().__init__(root=shared_root)
        self.cli = cli
        self.appdata_product = appdata_product
        self.wake_store = wake_store

    def list_sessions(self) -> list[SessionMeta]:
        out = [
            m
            for m in self._list_all()
            if _family_of_path(self.root, m.source_path) == "qoderwake"
        ]
        for m in out:
            # Group workers open with a harness prompt; that is not a title.
            if (m.title or "").startswith(
                ("You name the current internal session", "You are the Leader for a temporary")
            ) and "team-groups" in (m.cwd or ""):
                m.title = "团队工作会话 (QoderWake)"
        return self._split_toolloops(out)

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
from agent_handoff.parsers.base import Parser, db_version, probe_memo


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


def _row(content_json):
    """The row's envelope and block list, or None when the row is unreadable.

    `{"message": {role/model/usage/metrics/createdAt}, "blocks": […]}` — the
    envelope can be missing or the JSON unparsable, and a row that cannot be read
    renders nothing.
    """
    try:
        payload = json.loads(content_json or "{}")
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    msg = payload.get("message")
    return (msg if isinstance(msg, dict) else {}, payload.get("blocks") or [])


def _row_role(msg: dict, role_column) -> str:
    """Whose turn the row is: the envelope's role wins, the column is the fallback.

    Anything that is not a user or assistant turn contributes nothing, which is
    what `load()` does with a row whose role says otherwise. Measured on this
    machine's store: all 224 rows agree between the two, so the precedence decides
    nothing today — it is here so that the probe and the page read one role, not
    two that happen to match.
    """
    role = str(msg.get("role") or role_column or "")
    return role if role in ("user", "assistant") else ""


def _block_turn(parser: Parser, row_role: str, block):
    """One rendered message this block puts on the page, or None if it drops it.

    `thinking` and `tool` blocks are assistant lines whatever the row's own role
    says, and only `main_text` carries that role — so a user row whose last block
    is a tool call ends on an assistant line, and "the last row" is not the same
    question as "the last line". Measured on this machine's store the shape does
    not occur (112 user rows, every one a lone `main_text` block; the other 112
    rows are all `assistant` and 107 of them carry a tool block), so this is
    `load()`'s rule kept in one place rather than a behaviour anyone sees today.

    A tool's text is truncated to the 500 characters the page shows before it is
    cleaned: cleaning a different string is judging a different question.
    """
    if not isinstance(block, dict) or not row_role:
        return None
    btype = block.get("type")
    if btype not in ("thinking", "main_text", "tool"):
        return None
    praw = _text(block.get("content"))
    if btype == "tool":
        praw = praw[:500]
    text = parser.clean_text(praw)
    if not text or parser.is_noise(text):
        return None
    return (row_role if btype == "main_text" else "assistant"), btype, praw, text


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

    def peek_needs_reply(self, session_id: str) -> bool | None:
        """The last line the page would show, asked of the store directly.

        Round 58's `db_version`/`probe_memo` pair, because this is a scan rather
        than an index seek — `session_messages` has no index leading with
        `session_id` (checked against the live store's `sqlite_master`) — so the
        answer is cached per store change, not per list rebuild.
        """
        return probe_memo(
            str(self.db_path),
            session_id,
            db_version(self.db_path),
            lambda: self._needs_reply(session_id),
        )

    def _needs_reply(self, session_id: str) -> bool | None:
        # Uncapped and read lazily: a row can hold nothing that reaches the page
        # (an empty tool result, a thinking block that cleans to nothing), so the
        # walk goes back to the row that does — and a row cap that ran out would
        # answer `None` about a session the page can answer (the largest session on
        # this store holds 108 rows). The common case is one row, because the
        # newest row usually decides it; the worst case is the parse `load()`
        # already pays, and the answer is cached per store change.
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT role, content FROM session_messages WHERE session_id=?"
                    " ORDER BY created_at DESC, rowid DESC",
                    (session_id,),
                )
                for row in rows:
                    packed = _row(row["content"])
                    if packed is None:
                        continue
                    msg, blocks = packed
                    role = _row_role(msg, row["role"])
                    turns = [t for block in blocks if (t := _block_turn(self, role, block))]
                    if turns:
                        # The last thing the reader sees, not the row's own role: a
                        # user row whose final block is a tool call ends on an
                        # assistant line.
                        return turns[-1][0] == "user"
        except sqlite3.Error:
            return None
        return None

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

    def usage(self, session_id: str) -> dict | None:
        """Per-model tokens + TTFT from the message rows.

        Each assistant message carries ``usage`` (prompt/completion tokens)
        and ``metrics.time_first_token_millsec``. Aggregated here so the
        cockpit usage card shows the same numbers the app's own billing
        surface would.
        """
        if not self.available():
            return None
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT content FROM session_messages WHERE session_id=? AND role='assistant'",
                    (session_id,),
                ).fetchall()
        except sqlite3.Error:
            return None
        agg: dict[str, dict] = {}
        for (content,) in rows:
            try:
                payload = json.loads(content or "{}")
            except ValueError:
                continue
            msg = payload.get("message") if isinstance(payload, dict) else None
            if not isinstance(msg, dict):
                continue
            model = msg.get("model")
            name = model.get("name") if isinstance(model, dict) else None
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            metrics = msg.get("metrics") if isinstance(msg.get("metrics"), dict) else {}
            ti = usage.get("prompt_tokens")
            to = usage.get("completion_tokens")
            if not isinstance(ti, int) and not isinstance(to, int):
                continue
            a = agg.setdefault(
                str(name or "unknown"),
                {"calls": 0, "tokens_in": 0, "tokens_out": 0, "ttft": [], "reasoning": 0,
                 "cache_write": 0, "cache_read": 0},
            )
            a["calls"] += 1
            a["tokens_in"] += ti if isinstance(ti, int) else 0
            a["tokens_out"] += to if isinstance(to, int) else 0
            ttft = metrics.get("time_first_token_millsec")
            if isinstance(ttft, (int, float)):
                a["ttft"].append(ttft)
        if not agg:
            return None
        models = []
        tot_in = tot_out = tot_calls = 0
        for model, a in sorted(agg.items(), key=lambda kv: -kv[1]["tokens_out"]):
            ttft_list = a.pop("ttft")
            models.append(
                {
                    "model": model,
                    "calls": a["calls"],
                    "tokens_in": a["tokens_in"],
                    "tokens_out": a["tokens_out"],
                    "reasoning": a["reasoning"],
                    "cache_write": a["cache_write"],
                    "cache_read": a["cache_read"],
                    "avg_ttft_ms": round(sum(ttft_list) / len(ttft_list)) if ttft_list else None,
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

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        with self._connect() as con:
            try:
                sess = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
                if sess is None:
                    return None
                agent = con.execute(
                    "SELECT name FROM agents WHERE id=?", (sess["agent_id"],)
                ).fetchone()
                rows = con.execute(
                    # `rowid` makes the ordering of two rows sharing a `created_at`
                    # explicit. Without it SQLite leaves ties unspecified, and the
                    # probe (`ORDER BY created_at DESC, rowid DESC`) would be
                    # reading a last row this render does not produce. Measured on
                    # this store: 0 tied (session, instant) pairs in 224 rows, so
                    # no current answer depends on it.
                    "SELECT role, content, created_at FROM session_messages "
                    "WHERE session_id=? ORDER BY created_at, rowid",
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
            packed = _row(row["content"])
            if packed is None:
                continue
            msg, blocks = packed
            role = _row_role(msg, row["role"])
            if not role:
                continue
            model = msg.get("model")
            model_name = model.get("name") if isinstance(model, dict) else None
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            # One message row = one LLM call: its usage bills every assistant
            # block inside it (thinking + text + tool), not just main_text.
            ti = usage.get("prompt_tokens")
            to = usage.get("completion_tokens")
            ti = ti if isinstance(ti, int) else None
            to = to if isinstance(to, int) else None
            # Measured cost proxy: the store's own per-call completion time.
            metrics = msg.get("metrics") if isinstance(msg.get("metrics"), dict) else {}
            mt = metrics.get("time_completion_millsec")
            mt = mt if isinstance(mt, int) and mt >= 0 else None
            at = msg.get("createdAt") or row["created_at"]
            for block in blocks:
                # Counted whether or not the block renders: the store's tool call
                # is a fact about the run, and an empty result does not un-happen.
                if isinstance(block, dict) and block.get("type") == "tool":
                    tools["tool"] += 1
                    for p in self.extract_paths(block.get("metadata") or {}):
                        files[p] += 1
                turn = _block_turn(self, role, block)
                if turn is None:
                    continue
                who, btype, praw, text = turn
                if btype == "thinking":
                    messages.append(
                        self.msg(
                            who,
                            f"[思考] {praw}",
                            text=f"[思考] {text}",
                            at=at,
                            model=model_name or None,
                            tokens_in=ti,
                            tokens_out=to,
                            dur_ms=mt,
                        )
                    )
                elif btype == "main_text":
                    messages.append(
                        self.msg(
                            who,
                            praw,
                            text=text,
                            at=at,
                            model=model_name or None,
                            tokens_in=ti,
                            tokens_out=to,
                            dur_ms=mt,
                        )
                    )
                else:
                    messages.append(
                        self.msg(
                            who,
                            f"[工具] {praw}",
                            text=f"[工具] {text}",
                            at=at,
                            model=model_name or None,
                        )
                    )
        return self.build_raw(meta, messages, [], files, tools)

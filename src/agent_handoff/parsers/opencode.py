"""OpenCode parser — SQLite store at ~/.local/share/opencode/opencode.db.

Layout (verified live, 2026-09-01):
    session   id, title, directory, parent_id        (parent_id != null => sub-agent)
    message   id, session_id, time_created, data     (role/model/tokens/cost in data)
    part      message_id, session_id, data           (type: text|tool|reasoning|step-*)
    todo      session_id, content, status, priority

Message ``data`` carries genuine billing: ``tokens{input,output,reasoning,
cache{write,read}}``, ``cost`` (USD), ``providerID``/``modelID`` — the richest
per-turn accounting of any supported store. Sub-agent sessions keep their own
rows and are surfaced through ``parent_session_id`` rather than merged, because
OpenCode titles and addresses them as independent conversations ("@explore
subagent ...").
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections import Counter

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta, TodoItem, ts_to_iso
from agent_handoff.parsers.base import Parser


def _opencode_model(raw) -> str | None:
    """model is a JSON blob {"id","providerID","variant"}; render the id."""
    if not raw:
        return None
    if isinstance(raw, dict):
        return str(raw.get("id") or "") or None
    try:
        d = json.loads(raw)
        return str(d.get("id") or "") or None
    except (ValueError, TypeError):
        s = str(raw).strip()
        return s or None


def _opencode_permission(raw) -> str | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return str(raw.get("mode") or raw) or None
    return str(raw).strip() or None


class OpenCodeParser(Parser):
    cli = "opencode"

    def __init__(self, root=None) -> None:

        self.root = root or home() / ".local" / "share" / "opencode"

    def available(self) -> bool:
        return self._db().is_file()

    def _db(self):
        from pathlib import Path

        return Path(self.root) / "opencode.db"

    def _connect(self) -> sqlite3.Connection:
        # WAL files can be live; read-only URI avoids locking the app out.
        return sqlite3.connect(f"file:{self._db()}?mode=ro", uri=True)

    # -- discovery ----------------------------------------------------------

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        metas: list[SessionMeta] = []
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT s.id, s.title, s.directory, s.parent_id, s.agent, s.model, "
                    "MAX(m.time_created) "
                    "FROM session s LEFT JOIN message m ON m.session_id = s.id "
                    "GROUP BY s.id"
                ).fetchall()
        except sqlite3.Error:
            return []
        for sid, title, directory, parent_id, agent, model, last_ms in rows:
            metas.append(
                SessionMeta(
                    cli=self.cli,
                    session_id=str(sid),
                    title=str(title) if title else str(sid),
                    cwd=str(directory or ""),
                    updated_at=ts_to_iso(last_ms) if last_ms else None,
                    source_path=str(self._db()),
                    parent_session_id=str(parent_id) if parent_id else None,
                    model=_opencode_model(model),
                    notes=([f"agent:{agent}"] if agent else []),
                )
            )
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    # -- loading ------------------------------------------------------------

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """Every row the SQLite store holds for this session, all columns
        (message/part/todo/session), record-level JSON lines."""
        from agent_handoff.parsers.base import json_records_entry

        records: list[tuple[str, dict]] = []
        try:
            with self._connect() as con:
                for table in ("session", "message", "part", "todo"):
                    idcol = "id" if table == "session" else "session_id"
                    try:
                        cur = con.execute(f"SELECT * FROM {table} WHERE {idcol}=?", (session_id,))
                        cols = [d[0] for d in cur.description]
                        for row in cur.fetchall():
                            records.append((table, dict(zip(cols, row, strict=True))))
                    except sqlite3.Error:
                        continue
        except sqlite3.Error:
            return None
        if not records:
            return None
        return [json_records_entry(f"opencode/{session_id}.records.jsonl", records)]

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        try:
            with self._connect() as con:
                srow = con.execute(
                    "SELECT id, title, directory, parent_id, agent, model, "
                    "tokens_input, tokens_output, tokens_reasoning, "
                    "tokens_cache_read, tokens_cache_write, cost, permission, "
                    "time_compacting, version "
                    "FROM session WHERE id=?",
                    (session_id,),
                ).fetchone()
                if srow is None:
                    return None
                (
                    sid,
                    title,
                    directory,
                    parent_id,
                    agent,
                    model,
                    t_in,
                    t_out,
                    t_reas,
                    t_cr,
                    t_cw,
                    cost,
                    permission,
                    compacting,
                    version,
                ) = srow
                mrows = con.execute(
                    "SELECT id, time_created, data FROM message "
                    "WHERE session_id=? ORDER BY time_created",
                    (session_id,),
                ).fetchall()
                parts_by_msg: dict[str, list[dict]] = {}
                for p_mid, pdata in con.execute(
                    "SELECT message_id, data FROM part WHERE session_id=? ORDER BY time_created",
                    (session_id,),
                ):
                    try:
                        p = json.loads(pdata)
                    except (ValueError, TypeError):
                        continue
                    if p_mid:
                        parts_by_msg.setdefault(str(p_mid), []).append(p)
                trows = con.execute(
                    "SELECT content, status, priority FROM todo WHERE session_id=? "
                    "ORDER BY position",
                    (session_id,),
                ).fetchall()
        except sqlite3.Error:
            return None

        meta = SessionMeta(
            cli=self.cli,
            session_id=str(sid),
            title=str(title) if title else str(sid),
            cwd=str(directory or ""),
            source_path=str(self._db()),
            parent_session_id=str(parent_id) if parent_id else None,
            model=_opencode_model(model),
            tokens_in=int(t_in or 0) or None,
            tokens_out=int(t_out or 0) or None,
            permission=_opencode_permission(permission),
            notes=([f"agent:{agent}"] if agent else []),
        )
        if version and version != "local":
            meta.notes = [*meta.notes, f"version:{version}"]
        if compacting:
            meta.notes = [*meta.notes, f"compacted_at:{ts_to_iso(compacting)}"]
        if cost:
            meta.notes = [*meta.notes, f"session_cost_usd:{cost}"]

        messages: list[Message] = []
        files: dict[str, int] = {}
        tools: dict[str, int] = {}
        updated_ms: int | None = None
        for mid, time_created, mdata in mrows:
            try:
                d = json.loads(mdata)
            except (ValueError, TypeError):
                continue
            role = d.get("role")
            if role not in ("user", "assistant"):
                continue
            when = ts_to_iso(time_created)
            if time_created and (updated_ms is None or time_created > updated_ms):
                updated_ms = time_created

            texts: list[str] = []
            raws: list[str] = []
            for p in parts_by_msg.get(str(mid), []):
                ptype = p.get("type")
                if ptype == "text":
                    praw = p.get("text") or ""
                    t = self.clean_text(praw)
                    if t and not self.is_noise(t):
                        texts.append(t)
                        raws.append(praw)
                elif ptype == "tool":
                    name = str(p.get("tool") or "tool")
                    tools[name] = tools.get(name, 0) + 1
                    state = p.get("state") if isinstance(p.get("state"), dict) else {}
                    ti = state.get("input") if isinstance(state.get("input"), dict) else {}
                    for fp in self.extract_paths(ti):
                        files[fp] = files.get(fp, 0) + 1
            text = "\n".join(texts)
            if not text:
                continue

            tokens = d.get("tokens") if isinstance(d.get("tokens"), dict) else {}
            model = d.get("modelID") or ""
            messages.append(
                self.msg(
                    str(role),
                    "\n".join(raws),
                    text=text,
                    at=when,
                    model=str(model) if model and role == "assistant" else None,
                    tokens_in=tokens.get("input"),
                    tokens_out=tokens.get("output"),
                    tokens_reasoning=tokens.get("reasoning"),
                )
            )

        if updated_ms is not None:
            meta.updated_at = ts_to_iso(updated_ms)
        todos = [
            TodoItem(content=str(c), status=str(s or "pending"), priority=str(p or ""))
            for c, s, p in trows
        ]
        return self.build_raw(meta, messages, todos, Counter(files), Counter(tools))

    # -- billing ------------------------------------------------------------

    def usage(self, session_id: str) -> dict | None:
        """Per-model tokens + real USD cost from the message rows, checked
        against the session row's own ledger (tokens_input/output/…, cost).

        The message stream is per-turn truth; the session row is the product's
        own accounting. When they disagree the session row wins for totals —
        it is what the app's billing surface shows.
        """
        if not self.available():
            return None
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT data FROM message WHERE session_id=?", (session_id,)
                ).fetchall()
                ledger = con.execute(
                    "SELECT tokens_input, tokens_output, tokens_reasoning, "
                    "tokens_cache_read, tokens_cache_write, cost "
                    "FROM session WHERE id=?",
                    (session_id,),
                ).fetchone()
        except sqlite3.Error:
            return None
        agg: dict[str, dict] = {}
        cost_total = 0.0
        for (mdata,) in rows:
            try:
                d = json.loads(mdata)
            except (ValueError, TypeError):
                continue
            if d.get("role") != "assistant":
                continue
            model = str(d.get("modelID") or "unknown")
            tokens = d.get("tokens") if isinstance(d.get("tokens"), dict) else {}
            if not tokens:
                continue
            a = agg.setdefault(
                model,
                {
                    "calls": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "reasoning": 0,
                    "cache_write": 0,
                    "cache_read": 0,
                },
            )
            a["calls"] += 1
            a["tokens_in"] += int(tokens.get("input") or 0)
            a["tokens_out"] += int(tokens.get("output") or 0)
            a["reasoning"] += int(tokens.get("reasoning") or 0)
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            a["cache_write"] += int(cache.get("write") or 0)
            a["cache_read"] += int(cache.get("read") or 0)
            with contextlib.suppress(TypeError, ValueError):
                cost_total += float(d.get("cost") or 0)
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
                    "cache_write": a["cache_write"],
                    "cache_read": a["cache_read"],
                    "avg_ttft_ms": None,
                    "tok_per_s": None,
                }
            )
            tot_in += a["tokens_in"]
            tot_out += a["tokens_out"]
            tot_calls += a["calls"]
        totals: dict = {
            "calls": tot_calls,
            "tokens_in": tot_in,
            "tokens_out": tot_out,
            "cost_usd": round(cost_total, 6),
        }
        if ledger and any(v for v in ledger):
            # The product's own ledger overrules the summed turns.
            (l_in, l_out, l_reas, l_cr, l_cw, l_cost) = ledger
            totals.update(
                {
                    "calls": tot_calls,
                    "tokens_in": int(l_in or tot_in),
                    "tokens_out": int(l_out or tot_out),
                    "reasoning": int(l_reas or 0),
                    "cache_read": int(l_cr or 0),
                    "cache_write": int(l_cw or 0),
                    "cost_usd": round(float(l_cost or cost_total), 6),
                    "source": "session_ledger",
                }
            )
        return {"models": models, "totals": totals}

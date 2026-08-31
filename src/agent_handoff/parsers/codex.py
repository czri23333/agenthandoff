"""Codex CLI / Codex desktop parser — event-stream rollout JSONL.

Layout as measured on a real 2026-08 machine (not from documentation):

    $CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<ts>-<thread-id>.jsonl
    $CODEX_HOME/session_index.jsonl      {"id", "thread_name", "updated_at"}
    $CODEX_HOME/archived_sessions/       rotated copies

Default ``$CODEX_HOME`` is ``~/.codex``; the CLI honours the env var, so we must
too or the same install on another machine lands in a different place.

Each line is ``{"timestamp", "type", "payload"}`` and the dialogue has to be
*reconstructed* from an event stream — this was the shape of the earlier bugs:

  * identity: ``payload.id`` is this thread, ``payload.session_id`` is the ROOT
    session (equal to the parent's id for sub-agents). Reading them in the wrong
    priority registered every sub-agent under its parent's id, and ``load()``
    then matched filenames for the wrong thread;
  * assistant text arrives both as ``response_item/message`` and as
    ``response_item/agent_message`` + ``event_msg/agent_message``. The old parser
    only looked at ``message``, so a session could list fine and extract nothing;
  * tool activity is its own events (``function_call`` / ``function_call_output``),
    not tool blocks inside a message, so file anchors and tool counts were lost;
  * ``turn_context`` carries the model, ``event_msg/task_started`` carries
    ``model_context_window`` and ``token_count`` carries usage — which is what
    lets us tell a context-window death from a quota death.

Injected harness text (``developer`` role rows, the ``<app-context>`` block and
the ``# AGENTS.md instructions`` prelude) is not user speech: it is skipped as a
turn, but the instruction files it names are recorded as file anchors.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta, ts_to_iso
from agent_handoff.parsers.base import Parser, as_text_blocks, read_jsonl

# Text that opens an injected turn rather than something the human typed.
_INJECTED_PREFIXES = (
    "# AGENTS.md instructions",
    "<app-context>",
    "<INSTRUCTIONS>",
    "<system-reminder",
)


def codex_root() -> Path:
    """Store root honouring $CODEX_HOME, like the CLI itself does."""
    override = os.environ.get("CODEX_HOME", "").strip()
    base = Path(override).expanduser() if override else home() / ".codex"
    return base / "sessions"


def _codex_home() -> Path:
    """Deprecated module-level helper; prefer CodexParser._home().

    Kept only for callers that want the live machine's home. A parser aimed at a
    fixture tree must NOT use it: reading a fixture's titles from the real
    ~/.codex would make the fixture self-referential and unreproducible.
    """
    override = os.environ.get("CODEX_HOME", "").strip()
    return Path(override).expanduser() if override else home() / ".codex"


class CodexParser(Parser):
    cli = "codex"

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else codex_root()
        self._titles: dict[str, str] | None = None
        self._usage_cache: dict[str, dict] = {}

    def available(self) -> bool:
        return self.root.is_dir()

    # -- helpers --------------------------------------------------------------
    def _home(self) -> Path:
        """The CLI's data directory, derived from our own root.

        Fixture-ability depends on this: `with_root(tests/fixtures/...)` must read
        the session index and archived copies from inside the fixture, never from
        the live ~/.codex.
        """
        if self.root.name in ("sessions", "archived_sessions"):
            return self.root.parent
        return self.root

    def _files(self) -> list[Path]:
        if not self.available():
            return []
        out = list(self.root.rglob("rollout-*.jsonl"))
        if not out:  # older/other builds dropped the rollout- prefix
            out = [p for p in self.root.rglob("*.jsonl") if p.name != "session_index.jsonl"]
        archived = self._home() / "archived_sessions"
        if archived.is_dir():
            out.extend(archived.rglob("*.jsonl"))
        return sorted(set(out), key=lambda p: p.name)

    def _index_titles(self) -> dict[str, str]:
        """thread id -> human title, from the vendor's own session index."""
        if self._titles is not None:
            return self._titles
        titles: dict[str, str] = {}
        index = self._home() / "session_index.jsonl"
        if index.is_file():
            for row in read_jsonl(index):
                tid = str(row.get("id") or "")
                name = str(row.get("thread_name") or "").strip()
                if tid and name:
                    titles[tid] = name
        self._titles = titles
        return titles

    @staticmethod
    def _meta_from_header(path: Path, payload: dict, updated: str | None) -> SessionMeta:
        thread_id = str(payload.get("id") or path.stem.split("-")[-1])
        root_session = str(payload.get("session_id") or thread_id)
        src = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        spawn = {}
        if isinstance(src.get("subagent"), dict):
            spawn = src["subagent"].get("thread_spawn") or {}
        parent = payload.get("parent_thread_id") or spawn.get("parent_thread_id") or root_session
        if parent == thread_id:
            parent = None
        notes: list[str] = []
        if spawn.get("agent_path"):
            notes.append(f"agent_path:{spawn['agent_path']}")
        if spawn.get("agent_nickname"):
            notes.append(f"agent:{spawn['agent_nickname']}")
        if root_session != thread_id:
            notes.append(f"root_session:{root_session}")
        return SessionMeta(
            cli="codex",
            session_id=thread_id,
            title="",  # filled by the caller (index lookup beats the filename)
            cwd=str(payload.get("cwd") or ""),
            started_at=ts_to_iso(payload.get("timestamp")),
            updated_at=updated,
            model=str(payload.get("model") or payload.get("model_provider") or "") or None,
            source_path=str(path),
            origin=str(payload.get("originator") or "") or None,
            parent_session_id=parent,
            notes=notes,
        )

    def _file_meta(self, path: Path) -> SessionMeta | None:
        for row in read_jsonl(path, limit=8):
            if row.get("type") == "session_meta":
                try:
                    updated = ts_to_iso(int(path.stat().st_mtime * 1000))
                except OSError:
                    updated = None
                meta = self._meta_from_header(path, row.get("payload") or {}, updated)
                meta.title = self._title_for(meta, path)
                return meta
        return None

    def _title_for(self, meta: SessionMeta, path: Path) -> str:
        titles = self._index_titles()
        if meta.session_id in titles:
            return titles[meta.session_id]
        # Sub-agents are absent from the vendor index; their spawn record carries
        # a human-readable lane name, which beats a timestamped filename.
        lane = next((n.split(":", 1)[1] for n in meta.notes if n.startswith("agent_path:")), "")
        nick = next((n.split(":", 1)[1] for n in meta.notes if n.startswith("agent:")), "")
        if lane:
            return f"{lane.lstrip('/')}" + (f" ({nick})" if nick else "")
        return path.stem.replace("rollout-", "")[:80]

    # -- public API -----------------------------------------------------------
    def list_sessions(self) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        seen: set[str] = set()
        for path in self._files():
            meta = self._file_meta(path)
            if meta is None or meta.session_id in seen:
                continue
            seen.add(meta.session_id)
            metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def load(self, session_id: str) -> RawSession | None:
        for path in self._files():
            rows = read_jsonl(path)
            if not rows:
                continue
            header = next((r for r in rows if r.get("type") == "session_meta"), None)
            if header is None:
                continue
            try:
                updated = ts_to_iso(int(path.stat().st_mtime * 1000))
            except OSError:
                updated = None
            meta = self._meta_from_header(path, header.get("payload") or {}, updated)
            if meta.session_id != session_id:
                continue
            meta.title = self._title_for(meta, path)
            return self._build(meta, rows)
        return None

    def _build(self, meta: SessionMeta, rows: list[dict]) -> RawSession:
        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        context_window: int | None = None
        last_tokens: dict[str, int] = {}
        saw_completion = False
        model: str | None = None

        for row in rows:
            rtype = row.get("type")
            payload = row.get("payload") or {}
            ptype = str(payload.get("type") or "")
            when = ts_to_iso(row.get("timestamp"))

            def push(role: str, text: str, at: str | None) -> None:
                """Append, dropping the duplicate an event stream always has.

                Codex writes an assistant turn twice — once as ``response_item``
                (the API-visible message) and once as ``event_msg`` (the UI
                notification). Taking both doubles every reply, which quietly
                doubles the weight of assistant prose in any downstream summary.
                """
                if not text:
                    return
                last = messages[-1] if messages else None
                same = bool(last) and last.role == "assistant" and last.text.strip() == text.strip()
                if role == "assistant" and same:
                    return
                messages.append(Message(role=role, text=text, at=at))

            if rtype == "event_msg":
                if ptype == "task_started":
                    window = payload.get("model_context_window")
                    context_window = window if isinstance(window, int) else None
                elif ptype == "task_complete":
                    saw_completion = True
                elif ptype == "agent_message":
                    body = payload.get("message") or payload.get("text")
                    push("assistant", self._flatten(body), when)
                elif ptype == "token_count":
                    info = payload.get("info") or {}
                    used = info.get("total_token_usage") or info.get("last_token_usage") or {}
                    if isinstance(used, dict):
                        last_tokens.update({k: v for k, v in used.items() if isinstance(v, int)})
                continue

            if rtype == "turn_context":
                candidate = payload.get("model")
                if isinstance(candidate, str) and candidate:
                    model = candidate
                continue

            if rtype != "response_item":
                continue

            if ptype == "message":
                role = payload.get("role")
                if role not in ("user", "assistant"):
                    continue  # developer/system rows are harness injections
                text, tool_blocks = as_text_blocks(payload.get("content"))
                text = self.clean_text(text)
                if text.startswith(_INJECTED_PREFIXES):
                    for instruction in _instruction_paths(text):
                        files[instruction] += 1
                    continue
                if text and not self.is_noise(text):
                    push(str(role), text, when)
                for tb in tool_blocks:
                    name = str(tb.get("name") or "tool")
                    tools[name] += 1
                    ti = tb.get("input") if isinstance(tb.get("input"), dict) else {}
                    for path in _clean_paths(self.extract_paths(ti)):
                        files[path] += 1
            elif ptype == "agent_message":
                body = payload.get("text") or payload.get("message")
                push("assistant", self._flatten(body), when)
            elif ptype in ("function_call", "custom_tool_call"):
                name = str(payload.get("name") or "tool")
                tools[name] += 1
                args = payload.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                if isinstance(args, dict):
                    for path in _clean_paths(self.extract_paths(args)):
                        files[path] += 1

        if model and not meta.model:
            meta.model = model
        if context_window:
            meta.notes = [*meta.notes, f"context_window:{context_window}"]
        interruption = self._end_state(meta, messages, saw_completion, context_window, last_tokens)
        self._usage_cache[meta.session_id] = {
            "last_tokens": last_tokens,
            "context_window": context_window,
            "model": meta.model,
        }
        return self.build_raw(meta, messages, [], files, tools, interruption)

    @staticmethod
    def _flatten(content) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(b.get("text") or b.get("content") or "")
                for b in content
                if isinstance(b, dict)
            ]
            return "\n".join(p for p in parts if p).strip()
        return ""

    def _end_state(self, meta, messages, saw_completion, window, tokens):
        """Codex records no explicit error; infer only from hard evidence."""
        from agent_handoff.model import Interruption

        used = tokens.get("total_tokens") or tokens.get("input_tokens")
        if window and used and used >= int(window * 0.95):
            return Interruption(
                kind="context_exceeded",
                detail=f"last recorded usage {used} of a {window}-token window",
            )
        if messages and messages[-1].role == "user":
            return Interruption(
                kind="user_pending",
                detail="the newest turn is a user message with no reply",
                pending_user_text=messages[-1].text[:400],
            )
        if saw_completion:
            return Interruption(kind="clean")
        return Interruption(
            kind="unknown", detail="no task_complete event and no unanswered user turn"
        )

    def usage(self, session_id: str) -> dict | None:
        cache = getattr(self, "_usage_cache", {}) or {}
        got = cache.get(session_id)
        if not got or not got.get("last_tokens"):
            return None
        tokens = got["last_tokens"]
        rows = [
            {
                "model": got.get("model") or "unknown",
                "calls": 1,
                "tokens_in": tokens.get("input_tokens") or tokens.get("prompt_tokens"),
                "tokens_out": tokens.get("output_tokens") or tokens.get("completion_tokens"),
                "reasoning": tokens.get("reasoning_output_tokens"),
                "cache_write": None,
                "cache_read": tokens.get("cached_tokens"),
                "avg_ttft_ms": None,
                "tok_per_s": None,
            }
        ]
        total_in = rows[0]["tokens_in"] or 0
        total_out = rows[0]["tokens_out"] or 0
        totals = {"calls": 1, "tokens_in": total_in, "tokens_out": total_out}
        return {"models": rows, "totals": totals}

    def peek_status(self, session_id: str) -> str | None:
        """Cheap end-state: scan one file's event types, no full rebuild."""
        for path in self._files():
            if session_id not in path.name and session_id != path.stem.split("-")[-1]:
                continue
            rows = read_jsonl(path, limit=400)
            types = {str((r.get("payload") or {}).get("type")) for r in rows if r.get("type")}
            if "task_complete" in types:
                return "clean"
            return None
        return None


def _clean_paths(paths: list[str]) -> list[str]:
    """Strip shell quoting a path regex inevitably picks up at the edges."""
    cleaned: list[str] = []
    for p in paths:
        p = p.strip().strip("'\"")
        if p:
            cleaned.append(p)
    return cleaned


def _instruction_paths(text: str) -> list[str]:
    """Pull the instruction-file paths named by an injected AGENTS.md prelude."""
    return re.findall(r"[A-Za-z]:[\\/][^\s\"'<>|]*\bAGENTS\.md|(?<!\S)AGENTS\.md", text, re.I)

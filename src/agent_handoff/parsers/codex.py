"""Codex CLI / Codex desktop parser — event-stream rollout JSONL.

Layout as measured on a real 2026-08 machine (not from documentation):

    $CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<ts>-<thread-id>.jsonl
    $CODEX_HOME/session_index.jsonl      {"id", "thread_name", "updated_at"}
    $CODEX_HOME/archived_sessions/       rotated copies

Default ``$CODEX_HOME`` is ``~/.codex``; the CLI honours the env var, so we must
too or the same install on another machine lands in a different place.

Each line is ``{"timestamp", "type", "payload"}`` and the dialogue has to be
*reconstructed* from an event stream — this was the shape of the earlier bugs:

  * one session spans several files: ``rollout-<ts>-<id>.jsonl`` for the first
    run and ``rollout-<ts>-<id>_<continuation>.jsonl`` for each resume. Reading
    only the first showed turn one and silently dropped the rest, so every
    accessor here folds the thread's own files back together;
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
from typing import NamedTuple
from urllib.parse import unquote, urlparse

from agent_handoff.locations import home
from agent_handoff.model import (
    CompactionEvent,
    HistoryStart,
    Message,
    RawSession,
    SessionMeta,
    ts_to_iso,
)
from agent_handoff.parsers.base import Parser, as_text_blocks, read_jsonl

# A rollout filename carries the thread's UUID first; a continuation file
# appends a second one: ``rollout-<ts>-<thread-id>_<continuation>.jsonl``.
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class _Rollout(NamedTuple):
    """One rollout file: its path, its session header, and how old it is."""

    path: Path
    header: dict
    started_at: str | None
    mtime: float


def _filename_session_id(path: Path) -> str:
    """The thread id a rollout filename carries.

    Continuation files are ``rollout-<ts>-<thread-id>_<continuation>.jsonl``:
    the thread's own UUID is the *first* one in the stem (the rule the store's
    own stats tool uses), so prefer it. Older names with no UUID at all fall
    back to the last dash-separated token, minus any continuation suffix.
    """
    found = _UUID.findall(path.stem)
    if found:
        return found[0]
    tail = path.stem.split("-")[-1]
    return tail.split("_")[0] or tail


# Text that opens an injected turn rather than something the human typed.
_INJECTED_PREFIXES = (
    "# AGENTS.md instructions",
    "<app-context>",
    "<INSTRUCTIONS>",
    "<system-reminder",
)

# Rows this parser synthesizes to stand in for a product timeline element
# rather than for speech: a folded thinking block, a tool card, a sub-agent
# block. They are turns in the transcript but they are not the answer to a
# request, so per-request billing never settles onto one - the answer row keeps
# the numbers the store recorded for the request that produced it.
_HINT_PREFIXES = ("[思考]", "[工具", "[子代理]")


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

    def _usage_for(self, session_id: str) -> dict:
        """Cached usage, parsing the rollout once if nothing is cached yet.

        These numbers are produced while reading the session, so an accessor that
        refuses to read the session answers "no data" to any caller that asks
        before loading it - including the cockpit and `handoff list`.
        """
        if session_id not in self._usage_cache:
            self.load(session_id)
        return self._usage_cache.get(session_id) or {}

    def last_request_tokens(self, session_id: str) -> dict:
        """The most recent `token_count` record for this session, if there was one."""
        return dict(self._usage_for(session_id).get("last_tokens") or {})

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
        thread_id = str(payload.get("id") or _filename_session_id(path))
        root_session = str(payload.get("session_id") or thread_id)
        src = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        spawn = {}
        if isinstance(src.get("subagent"), dict):
            spawn = src["subagent"].get("thread_spawn") or {}
        # A sub-agent names its spawner; a *forked* thread names the thread it was
        # cut from, which is the only link it has. They are the same value on this
        # store (21 of 21), so this is a fallback rather than a change.
        parent = (
            payload.get("parent_thread_id")
            or spawn.get("parent_thread_id")
            or payload.get("forked_from_id")
            or root_session
        )
        if parent == thread_id:
            parent = None
        notes: list[str] = []
        if spawn.get("agent_path"):
            notes.append(f"agent_path:{spawn['agent_path']}")
        if spawn.get("agent_nickname"):
            notes.append(f"agent:{spawn['agent_nickname']}")
        if root_session != thread_id:
            notes.append(f"root_session:{root_session}")
        # What the product itself calls this thread. "user" is an ordinary
        # conversation and says nothing; the other two are what the app groups
        # child runs by, and SessionMeta.task_type is the field for that.
        thread_source = str(payload.get("thread_source") or "").strip()
        # The revision the session ran on, as the store recorded it at the time.
        header_git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
        git_branch = str(header_git.get("branch") or "").strip() or None
        git_commit = str(header_git.get("commit_hash") or "").strip() or None
        return SessionMeta(
            cli="codex",
            session_id=thread_id,
            git_branch=git_branch,
            git_commit=git_commit,
            task_type=(
                thread_source if thread_source in ("subagent", "agent_created_thread") else None
            ),
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

    @staticmethod
    def _header_payload(path: Path, limit: int = 8) -> dict | None:
        """The file's ``session_meta`` payload, or None when it has no header."""
        for row in read_jsonl(path, limit=limit):
            if row.get("type") == "session_meta":
                payload = row.get("payload")
                return payload if isinstance(payload, dict) else {}
        return None

    def _thread_of(self, path: Path, header: dict) -> str:
        """This file's *thread* id: the header's ``id`` first, filename second.

        ``payload.session_id`` is the ROOT session - a sub-agent shares its
        parent's root while being a different thread - so it never groups
        files. Only ``id`` (this thread) or the filename names a session.
        """
        ident = str(header.get("id") or "").strip()
        return ident or _filename_session_id(path)

    def _rollouts(self) -> list[_Rollout]:
        """Every readable rollout file with its header, in a stable order."""
        out: list[_Rollout] = []
        for path in self._files():
            header = self._header_payload(path)
            if header is None:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            out.append(_Rollout(path, header, ts_to_iso(header.get("timestamp")), mtime))
        return out

    @staticmethod
    def _oldest_first(rollouts: list[_Rollout]) -> list[_Rollout]:
        """Oldest file first: header time, then mtime, then filename."""
        return sorted(rollouts, key=lambda r: (r.started_at or "", r.mtime, r.path.name))

    def _session_files(self, session_id: str) -> list[_Rollout]:
        """Every rollout file of one thread, oldest first.

        One Codex session can span several rollout files. Treating each file as
        a session made ``load()`` read turn one of eight and silently drop the
        rest, so every accessor folds them by thread identity - never by the
        root session id, which sub-agents share with their parent.
        """
        return self._oldest_first(
            [r for r in self._rollouts() if self._thread_of(r.path, r.header) == session_id]
        )

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
        """One row per thread, even when the thread spans several files.

        ``started_at``/``source_path`` come from the oldest file (where the
        thread began) and ``updated_at`` from the newest file's mtime, so a
        resumed session stays one row, stamped with its last activity.
        """
        by_thread: dict[str, list[_Rollout]] = {}
        for rollout in self._rollouts():
            thread = self._thread_of(rollout.path, rollout.header)
            by_thread.setdefault(thread, []).append(rollout)
        metas: list[SessionMeta] = []
        for rollouts in by_thread.values():
            ordered = self._oldest_first(rollouts)
            oldest = ordered[0]
            updated = ts_to_iso(int(max(r.mtime for r in ordered) * 1000))
            meta = self._meta_from_header(oldest.path, oldest.header, updated)
            if meta.started_at is None:
                meta.started_at = next((r.started_at for r in ordered if r.started_at), None)
            meta.title = self._title_for(meta, oldest.path)
            metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """The thread's rollout event streams, verbatim - one entry per file,
        oldest first. Every event the product appended (agent_message,
        function_call, token_count, ...) rides along unchanged."""
        from agent_handoff.parsers.base import file_entry

        entries: list[dict] = []
        for rollout in self._session_files(session_id):
            try:
                raw = rollout.path.read_bytes()
            except OSError:
                continue
            try:
                rel = str(rollout.path.resolve().relative_to(self.root.resolve()))
            except (ValueError, OSError):
                rel = str(rollout.path)
            entries.append(file_entry(rollout.path, raw, rel))
        return entries or None

    def load(self, session_id: str) -> RawSession | None:
        """The whole thread: every rollout file whose header id is this session.

        Rows from all of its files are concatenated in record-timestamp order
        (equal timestamps keep per-file order, files oldest first) and built
        exactly once, so ``rollout-...-<id>.jsonl`` plus each
        ``rollout-...-<id>_<continuation>.jsonl`` read back as one session.
        """
        rollouts = self._session_files(session_id)
        if not rollouts:
            return None
        oldest = rollouts[0]
        updated = ts_to_iso(int(max(r.mtime for r in rollouts) * 1000))
        meta = self._meta_from_header(oldest.path, oldest.header, updated)
        if meta.started_at is None:
            meta.started_at = next((r.started_at for r in rollouts if r.started_at), None)
        meta.title = self._title_for(meta, oldest.path)
        return self._build(meta, self._merged_rows(rollouts))

    @staticmethod
    def _merged_rows(rollouts: list[_Rollout]) -> list[dict]:
        """Rows of every file in timestamp order; ties keep per-file order.

        ``sorted`` is stable, so collecting rows file by file (oldest first)
        and sorting on the record timestamp leaves a file's own order intact
        wherever two records share a timestamp. Rows with no timestamp sort
        first as a group, in that same file order.
        """
        rows: list[dict] = []
        for rollout in rollouts:
            rows.extend(read_jsonl(rollout.path))
        return sorted(rows, key=lambda row: ts_to_iso(row.get("timestamp")) or "")

    def _build(self, meta: SessionMeta, rows: list[dict]) -> RawSession:
        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        context_window: int | None = None
        last_tokens: dict[str, int] = {}  # the most recent request
        total_tokens: dict[str, int] = {}  # the session sum
        requests = 0
        saw_completion = False
        model: str | None = None
        pending_tokens: dict = {}
        # Non-null only: the store's own quota truth, collaboration state and
        # the permissions the run was fenced with.
        rate_limits: dict | None = None
        world_agents: str | None = None
        turn_policy: dict[str, str] = {}
        # ``task_complete`` and ``turn_aborted`` are the two ways a turn ends, so
        # the newest of them is the end state - which this reader used to infer
        # from the order of the messages instead of reading.
        aborts: list[dict] = []
        last_turn_end = ""
        # The product's own compaction dividers, in order. Each one measures the
        # window it closed (the last request before it) against the window that
        # replaced it (the first request after it).
        compactions: list[CompactionEvent] = []
        awaiting_post: CompactionEvent | None = None
        # ``token_usage_record`` is the same accounting as ``token_count`` in a
        # newer spelling; a session carries one or the other (measured
        # 2026-09-12: 19 files carry token_count alone, 0 carry the record
        # alone), so this stays a fallback and can never double the call count.
        recorded_last: dict[str, int] = {}
        recorded_total: dict[str, int] = {}
        recorded_calls = 0
        header_facts: list[str] = []
        history_start: HistoryStart | None = None
        goal: str | None = None
        settings: dict[str, str] = {}
        subagents_seen: set[tuple[str, str]] = set()

        for row in rows:
            rtype = row.get("type")
            payload = row.get("payload") or {}
            ptype = str(payload.get("type") or "")
            when = ts_to_iso(row.get("timestamp"))

            def push(
                role: str,
                text: str,
                at: str | None,
                raw: str | None = None,
                model: str | None = None,
            ) -> None:
                """Append, dropping the duplicate an event stream always has.

                Codex writes an assistant turn twice — once as ``response_item``
                (the API-visible message) and once as ``event_msg`` (the UI
                notification). Taking both doubles every reply, which quietly
                doubles the weight of assistant prose in any downstream summary.
                A pending per-request billing (from the preceding token_count
                event) settles onto the next assistant turn; the product emits
                usage after the request it measures.
                """
                if not text:
                    return
                last = messages[-1] if messages else None
                # The stream writes an assistant turn twice (response_item +
                # event_msg); a tool card repeated twice is a tool the run
                # really called twice, so only plain turns collapse.
                same = (
                    bool(last)
                    and last.role == "assistant"
                    and last.text.strip() == text.strip()
                    and not text.startswith(_HINT_PREFIXES)
                )
                if role == "assistant" and same:
                    return
                msg = self.msg(role, raw if raw is not None else text, text=text, at=at)
                if role == "assistant":
                    if model:
                        msg.model = model
                    if not text.startswith(_HINT_PREFIXES):
                        pending = pending_tokens.get("pending")
                        if pending:
                            msg.tokens_in = pending.get("in")
                            msg.tokens_out = pending.get("out")
                            msg.tokens_reasoning = pending.get("reasoning")
                            pending_tokens.pop("pending", None)
                messages.append(msg)

            if rtype == "session_meta":
                # Facts about the *session* that no later row repeats: where the
                # working tree stood when it ran, and whether this file is the
                # whole conversation. 26 sessions on this store start mid-history
                # (their earlier turns live in the thread they forked from).
                git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
                branch = str(git.get("branch") or "").strip()
                commit = str(git.get("commit_hash") or "").strip()
                if branch or commit:
                    where = f"{branch or 'detached'}@{commit[:7]}" if commit else branch
                    header_facts.append(f"git:{where}")
                ordinal = payload.get("subagent_history_start_ordinal")
                if isinstance(ordinal, int) and ordinal > 0:
                    origin = str(meta.parent_session_id or "").strip()
                    header_facts.append(
                        f"history_start:{ordinal}" + (f" of {origin}" if origin else "")
                    )
                    history_start = HistoryStart(
                        ordinal=ordinal,
                        parent_session_id=origin,
                        # The row's timestamp is the usual source; the header
                        # payload carries its own for the builds that omit it,
                        # and the marker has to sort before the first turn.
                        at=when or ts_to_iso(payload.get("timestamp")),
                    )
                continue

            if rtype == "event_msg":
                if ptype == "task_started":
                    window = payload.get("model_context_window")
                    context_window = window if isinstance(window, int) else None
                elif ptype == "task_complete":
                    saw_completion = True
                    last_turn_end = "complete"
                elif ptype == "turn_aborted":
                    # The product's own record that the user stopped a turn.
                    aborts.append(payload if isinstance(payload, dict) else {})
                    last_turn_end = "aborted"
                elif ptype == "thread_goal_updated":
                    # The goal banner the app shows above the transcript.
                    state = payload.get("goal") if isinstance(payload.get("goal"), dict) else {}
                    objective = " ".join(str(state.get("objective") or "").split())
                    status = str(state.get("status") or "").strip()
                    if objective or status:
                        goal = f"{status or 'unknown'}:{objective[:400]}"
                elif ptype == "thread_settings_applied":
                    # What the thread was configured to run as: the model chip
                    # the app shows, and the provider and tier behind it.
                    applied_settings = payload.get("thread_settings")
                    applied_settings = (
                        applied_settings if isinstance(applied_settings, dict) else {}
                    )
                    candidate = applied_settings.get("model")
                    if isinstance(candidate, str) and candidate and not model:
                        model = candidate
                    for key, note in (
                        ("model_provider_id", "provider"),
                        ("service_tier", "service_tier"),
                    ):
                        val = applied_settings.get(key)
                        if isinstance(val, str) and val.strip():
                            settings[note] = val.strip()[:80]
                elif ptype == "item_completed":
                    # The card the product finished drawing. Most item kinds
                    # repeat a record already read above; these three say
                    # something no other row does.
                    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
                    itype = str(item.get("type") or "")
                    if itype == "FileChange":
                        # What the turn actually wrote, each change with its
                        # unified diff. The tool-argument pass above is a
                        # best-effort read of prose; this is the record.
                        changes = item.get("changes")
                        for changed in changes if isinstance(changes, dict) else ():
                            files[str(changed)] += 1
                    elif itype == "ImageView":
                        viewed = _file_url_to_path(str(item.get("path") or ""))
                        if viewed:
                            files[viewed] += 1
                    elif itype == "SubAgentActivity":
                        # The sub-agent lane the app nests under this thread.
                        child = str(item.get("agent_thread_id") or "").strip()
                        lane = str(item.get("agent_path") or "").strip()
                        kind = str(item.get("kind") or "activity").strip()
                        key = (kind, child or lane)
                        if (child or lane) and key not in subagents_seen:
                            subagents_seen.add(key)
                            line = " ".join(part for part in (kind, lane) if part)
                            push(
                                "assistant",
                                f"[子代理] {line}" + (f" → {child}" if child else ""),
                                when,
                                model=model,
                            )
                elif ptype == "agent_message":
                    body = payload.get("message") or payload.get("text")
                    push("assistant", self._flatten(body), when, model=model)
                elif ptype == "token_count":
                    info = payload.get("info") or {}
                    # Two different quantities live in one record.
                    # `last_token_usage` is the size of that one request (its
                    # input grows with the context: 16688 -> 79997 -> 138122 in a
                    # real rollout), which is what pressure and `context_exceeded`
                    # must be measured against. `total_token_usage` is the session
                    # sum - the right number for a usage table and the wrong one
                    # for either, which is what this branch used to do.
                    recent = info.get("last_token_usage")
                    if awaiting_post is not None:
                        # The window that replaced a compacted one: the first
                        # request after the divider, measured rather than
                        # modelled.
                        after = recent.get("input_tokens") if isinstance(recent, dict) else None
                        if isinstance(after, int):
                            awaiting_post.post_tokens = after
                            awaiting_post = None
                    if isinstance(recent, dict):
                        last_tokens.update({k: v for k, v in recent.items() if isinstance(v, int)})
                        bill = {
                            "in": recent.get("input_tokens"),
                            "out": recent.get("output_tokens"),
                        }
                        reasoning = recent.get("reasoning_output_tokens")
                        reasoning = reasoning if isinstance(reasoning, int) else None
                        if isinstance(bill["in"], int) or isinstance(bill["out"], int):
                            # Settle onto the latest answer turn that still has
                            # no billing; otherwise the next one takes it. A
                            # thinking block or a tool card is skipped: the
                            # request paid for the answer, and the store's own
                            # reasoning count belongs beside it.
                            settled = False
                            bill_in = bill["in"] if isinstance(bill["in"], int) else None
                            bill_out = bill["out"] if isinstance(bill["out"], int) else None
                            for m in reversed(messages):
                                if m.role != "assistant":
                                    continue
                                if (m.text or "").startswith(_HINT_PREFIXES):
                                    continue
                                if m.tokens_in is None and m.tokens_out is None:
                                    m.tokens_in = bill_in
                                    m.tokens_out = bill_out
                                    m.tokens_reasoning = reasoning
                                    if model and not m.model:
                                        m.model = model
                                    settled = True
                                break
                            if not settled:
                                pending_tokens["pending"] = {**bill, "reasoning": reasoning}
                    cumulative = info.get("total_token_usage")
                    if isinstance(cumulative, dict):
                        total_tokens.update(
                            {k: v for k, v in cumulative.items() if isinstance(v, int)}
                        )
                    requests += 1
                elif ptype in ("rate_limits", "rate_limit"):
                    # The store's own quota truth. Only non-null claims count:
                    # a row of nulls is "no signal", not "no quota".
                    info = payload.get("info") if isinstance(payload.get("info"), dict) else payload
                    kept = {k: v for k, v in info.items() if v is not None and k != "type"}
                    if kept:
                        rate_limits = kept
                continue

            if rtype == "compacted":
                # The divider the app draws in the timeline. window_number is
                # the only reason the store states, and the two token counts are
                # the requests that bracket the divider.
                window = payload.get("window_number")
                event = CompactionEvent(
                    at=when,
                    reason=f"window {window}" if isinstance(window, int) else "compacted",
                    pre_tokens=last_tokens.get("input_tokens"),
                    auto=True,
                )
                compactions.append(event)
                awaiting_post = event
                continue

            if rtype == "token_usage_record":
                # The newer spelling of token_count, and the only usage some
                # builds write. Kept aside so the two can never be added up.
                per_call = payload.get("usage")
                if isinstance(per_call, dict):
                    recorded_last.update(
                        {k: v for k, v in per_call.items() if isinstance(v, int)}
                    )
                thread_total = payload.get("thread_token_usage")
                if isinstance(thread_total, dict):
                    recorded_total.update(
                        {k: v for k, v in thread_total.items() if isinstance(v, int)}
                    )
                recorded_calls += 1
                continue

            if rtype == "world_state":
                # The multi-agent collaboration state the product keeps.
                state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
                agents = state.get("agents_md")
                if isinstance(agents, dict) and agents.get("text"):
                    world_agents = str(agents["text"])[:2000]
                elif isinstance(state.get("text"), str) and state["text"].strip():
                    world_agents = state["text"][:2000]
                continue

            if rtype == "turn_context":
                candidate = payload.get("model")
                if isinstance(candidate, str) and candidate:
                    model = candidate
                # The permissions this turn ran fenced with (what the app shows
                # for the turn: sandbox/approval/collaboration posture).
                for key in ("sandbox_policy", "approval_policy", "collaboration_mode"):
                    val = payload.get(key)
                    if val and key not in turn_policy:
                        # A dict here is a nested policy ({"type":
                        # "workspace-write", "writable_roots": [...]}). str() put a
                        # Python repr in the cockpit's facts list
                        # ({'type': 'danger-full-access'}); the same bytes as JSON are
                        # the same fact in a notation the reader does not have to
                        # translate.
                        if isinstance(val, (dict, list)):
                            turn_policy[key] = json.dumps(
                                val, ensure_ascii=False, separators=(",", ":")
                            )[:120]
                        else:
                            turn_policy[key] = str(val)[:120]
                continue

            if rtype != "response_item":
                continue

            if ptype == "message":
                role = payload.get("role")
                if role not in ("user", "assistant"):
                    continue  # developer/system rows are harness injections
                text, tool_blocks = as_text_blocks(payload.get("content"))
                raw = text
                text = self.clean_text(text)
                if text.startswith(_INJECTED_PREFIXES):
                    for instruction in _instruction_paths(text):
                        files[instruction] += 1
                    continue
                if text and not self.is_noise(text):
                    push(str(role), text, when, raw, model=model)
                for tb in tool_blocks:
                    name = str(tb.get("name") or "tool")
                    tools[name] += 1
                    ti = tb.get("input") if isinstance(tb.get("input"), dict) else {}
                    for path in _clean_paths(self.extract_paths(ti)):
                        files[path] += 1
            elif ptype == "reasoning":
                # The model's own thinking. The store keeps it verbatim in
                # content[*].text when the provider exposes it and as
                # encrypted_content when it does not (measured 2026-09-12: 4456
                # of 4494 rows carry text), and the product timeline folds it
                # under the turn - the [思考] row the jsonl-family parsers
                # already emit for the same thing.
                thought = self._reasoning_text(payload)
                if thought:
                    cleaned = self.clean_text(thought)
                    if cleaned:
                        push(
                            "assistant",
                            f"[思考] {cleaned}",
                            when,
                            f"[思考] {thought}",
                            model=model,
                        )
            elif ptype == "agent_message":
                body = payload.get("text") or payload.get("message")
                push("assistant", self._flatten(body), when, model=model)
            elif ptype in ("function_call", "custom_tool_call"):
                name = str(payload.get("name") or "tool")
                tools[name] += 1
                args = payload.get("arguments")
                # custom_tool_call carries the same idea as a bare string
                # (input): a patch, a script, a command line.
                given = args if isinstance(args, str) else str(payload.get("input") or "")
                hint_from: object = args if args is not None else payload.get("input")
                if isinstance(args, str):
                    # Exit code / wall time live on the paired output row; the
                    # arguments arrive as a JSON string, not a dict.
                    try:
                        args = json.loads(args)
                    except ValueError:
                        cmd = self._shell_command(args)
                        if cmd:
                            for path in _clean_paths(self.extract_paths({"command": cmd})):
                                files[path] += 1
                        args = {}
                if isinstance(args, dict):
                    for path in _clean_paths(self.extract_paths(args)):
                        files[path] += 1
                    body = json.dumps(args, ensure_ascii=False, indent=1)
                else:
                    body = given
                push(
                    "assistant",
                    self._tool_text(name, hint_from, body),
                    when,
                    json.dumps(payload, ensure_ascii=False)[:2000],
                    model=model,
                )
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                # "Exit code: 0\nWall time: 0.2 seconds\nOutput:\n…" — the
                # product's own execution record. Non-zero exits and slow
                # walls are failure signal, so keep them as notes.
                out = str(payload.get("output") or "")
                # The store spells a finished command two ways and the newer
                # build uses the second: "Exit code: 0" (custom tool calls) and
                # "Process exited with code 1" (exec_command). Reading only the
                # first made 271 failed commands in one session look like no
                # failure at all.
                head = out[:400]
                code = re.search(r"(?:Exit code:|Process exited with code)\s*(-?\d+)", head)
                wall = re.search(r"Wall time:\s*([\d.]+)\s*seconds", head)
                if code and code.group(1) != "0":
                    tools[f"exit:{code.group(1)}"] += 1
                if wall:
                    try:
                        if float(wall.group(1)) >= 60:
                            tools["slow_call>=60s"] += 1
                    except ValueError:
                        pass
            elif ptype == "tool_search_call":
                # The agent asking the harness for a tool: a call like any
                # other, so it counts and it shows. The paired output row
                # carries no exit code and no wall clock, so it is not a card.
                tools["tool_search"] += 1
                args = payload.get("arguments")
                args = args if isinstance(args, dict) else {}
                push(
                    "assistant",
                    self._tool_text("tool_search", args, json.dumps(args, ensure_ascii=False)),
                    when,
                    json.dumps(payload, ensure_ascii=False)[:2000],
                    model=model,
                )
            elif ptype == "web_search_call":
                action = payload.get("action")
                action = action if isinstance(action, dict) else {}
                tools["web_search"] += 1
                push(
                    "assistant",
                    self._tool_text("web_search", action, json.dumps(action, ensure_ascii=False)),
                    when,
                    json.dumps(payload, ensure_ascii=False)[:2000],
                    model=model,
                )

        if model and not meta.model:
            meta.model = model
        if not last_tokens and not total_tokens and recorded_calls:
            # No token_count at all: the newer spelling is the only usage this
            # session recorded, and it is read here so the two can never sum.
            last_tokens.update(recorded_last)
            total_tokens.update(recorded_total)
            requests += recorded_calls
        # A thread with several pages can repeat a header fact; each one is a
        # single fact about the session.
        seen_facts = set(meta.notes)
        meta.notes = [
            *meta.notes,
            *(f for f in header_facts if not (f in seen_facts or seen_facts.add(f))),
        ]
        if goal:
            meta.notes = [*meta.notes, f"goal:{goal}"]
        for key, val in settings.items():
            meta.notes = [*meta.notes, f"{key}:{val}"]
        if context_window:
            meta.notes = [*meta.notes, f"context_window:{context_window}"]
        for key, val in turn_policy.items():
            meta.notes = [*meta.notes, f"{key}:{val}"]
        if rate_limits:
            claims = ", ".join(f"{k}={v}" for k, v in rate_limits.items())
            meta.notes = [*meta.notes, f"rate_limits:{claims}"]
        interruption = self._end_state(
            meta,
            messages,
            saw_completion,
            context_window,
            last_tokens,
            aborts,
            last_turn_end,
        )
        self._usage_cache[meta.session_id] = {
            "last_tokens": last_tokens,
            "total_tokens": total_tokens,
            "requests": requests,
            "context_window": context_window,
            "model": meta.model,
        }
        raw = self.build_raw(meta, messages, [], files, tools, interruption)
        raw.compactions = compactions
        raw.history_start = history_start
        if world_agents:
            # Collaboration snapshot the product keeps (AGENTS.md excerpt).
            # A head fits notes; the full text stays in raw_archive verbatim.
            head = " ".join(world_agents.split())[:400]
            raw.meta.notes = [*raw.meta.notes, f"world_state:{head}"]
        return raw

    @staticmethod
    def _shell_command(args: str) -> str:
        """Pull the command out of a JSON-encoded arguments string."""
        m = re.search(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"', args)
        if not m:
            return ""
        try:
            return json.loads(f'"{m.group(1)}"')
        except ValueError:
            return m.group(1)

    @staticmethod
    def _flatten(content) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(b.get("text") or b.get("content") or "") for b in content if isinstance(b, dict)
            ]
            return "\n".join(p for p in parts if p).strip()
        return ""

    @staticmethod
    def _reasoning_text(payload: dict) -> str:
        """The readable thinking text, or "" when the store kept only ciphertext.

        Blocks arrive as content[{type: reasoning_text}] and, in the older
        spelling, as summary[{type: summary_text}]. An empty text beside an
        encrypted_content is the store saying "this request's thinking is not
        ours to read", which is not the same as having something to show.
        """
        for key in ("content", "summary"):
            parts: list[str] = []
            for block in payload.get(key) or []:
                if not isinstance(block, dict):
                    continue
                if str(block.get("type") or "") not in ("reasoning_text", "text", "summary_text"):
                    continue
                text = str(block.get("text") or "").strip()
                if text:
                    parts.append(text)
            if parts:
                return "\n".join(parts)
        return ""

    @staticmethod
    def _tool_hint(args) -> str:
        """The one argument a human would name the call by, on one line."""
        if isinstance(args, str):
            head = args.strip().splitlines()[0] if args.strip() else ""
            return " ".join(head.split())[:80]
        if isinstance(args, dict):
            for key in ("command", "cmd", "file_path", "path", "query", "pattern", "url"):
                val = args.get(key)
                if isinstance(val, str) and val.strip():
                    return " ".join(val.split())[:80]
            queries = args.get("queries")
            if isinstance(queries, list) and queries and isinstance(queries[0], str):
                return " ".join(queries[0].split())[:80]
        return ""

    def _tool_text(self, name: str, hint_from, body: str) -> str:
        """A tool card: the head names the call, the body is what it was given.

        The shape web/src/views/SessionDetail.tsx already folds into a card
        (head = the first line, expanded body = the rest), and the same one the
        jsonl-family parsers emit for their tool rows.
        """
        hint = self._tool_hint(hint_from)
        head = f"[工具 {name} · {hint}]" if hint else f"[工具 {name}]"
        body = body.strip()
        if not body:
            return head
        return f"{head}\n{body[:600]}"

    def _end_state(self, meta, messages, saw_completion, window, tokens, aborts, last_kind):
        """Codex records no explicit error; infer only from hard evidence."""
        from agent_handoff.model import Interruption

        used = tokens.get("total_tokens") or tokens.get("input_tokens")
        if window and used and used >= int(window * 0.95):
            return Interruption(
                kind="context_exceeded",
                detail=f"last recorded usage {used} of a {window}-token window",
            )
        if aborts and last_kind == "aborted":
            # The store said so: the newest turn ended with turn_aborted, which
            # is the user stopping it. Reading the message order instead called
            # this "an unanswered user message".
            last = aborts[-1]
            secs = last.get("duration_ms")
            ran = f" after {round(secs / 1000)}s" if isinstance(secs, int) and secs > 0 else ""
            how = (
                f"{len(aborts)} turns were interrupted"
                if len(aborts) > 1
                else "the turn was interrupted"
            )
            return Interruption(
                kind="cancelled",
                detail=f"{how}{ran} (store reason: {last.get('reason') or 'unknown'})",
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
        """Cumulative accounting for a session: the whole run, not the last call."""
        got = self._usage_for(session_id)
        if not got.get("total_tokens"):
            return None
        tokens = got["total_tokens"]
        calls = got.get("requests") or 1
        rows = [
            {
                "model": got.get("model") or "unknown",
                "calls": calls,
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
        totals = {"calls": calls, "tokens_in": total_in, "tokens_out": total_out}
        return {"models": rows, "totals": totals}

    def peek_status(self, session_id: str) -> str | None:
        """Cheap end-state: scan event types, no full rebuild.

        A resumed session is clean when *any* of its files recorded
        ``task_complete`` - the newest file often holds only the follow-up.
        """
        for rollout in self._session_files(session_id):
            rows = read_jsonl(rollout.path, limit=400)
            types = {str((r.get("payload") or {}).get("type")) for r in rows if r.get("type")}
            if "task_complete" in types:
                return "clean"
        return None


def _file_url_to_path(value: str) -> str:
    """A store file URL as a path: ``file:///C:/x/y.png`` -> ``C:/x/y.png``.

    The product stores the URL it displays; the cockpit ranks paths, so the
    scheme and the slash in front of a drive letter come off. Anything that is
    not a file URL is returned untouched.
    """
    value = value.strip()
    if not value.lower().startswith("file://"):
        return value
    parsed = urlparse(value)
    path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc.lower() not in ("", "localhost"):
        return f"//{parsed.netloc}{path}"
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        return path[1:]
    return path


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

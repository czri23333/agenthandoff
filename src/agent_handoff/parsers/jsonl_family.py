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

import contextlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Interruption, Message, RawSession, SessionMeta, TodoItem, ts_to_iso
from agent_handoff.parsers.base import Parser, as_text_blocks, file_entry, read_jsonl


def _tail_rows(path: Path, max_bytes: int = 65536) -> list[dict]:
    """The last records of a JSONL file, without reading the whole thing.

    The newest timestamp lives at the end of a long transcript, and `stat().mtime`
    is not it: mtime is when the file was copied, restored or checked out.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
                handle.readline()  # drop the fragment of a partial line
            payload = handle.read()
    except OSError:
        return []
    rows: list[dict] = []
    for line in payload.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _tail_lines(path: Path, max_bytes: int) -> list[bytes]:
    """The last whole lines of a file, as bytes.

    Bytes rather than parsed records because a tail is read to *find* one row: a
    qoder transcript's non-dialogue records (attachments, history snapshots) run
    to tens of kilobytes each, so decoding a window costs more than reading it.
    The caller tests each line for a role token and parses only the candidates.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            start = max(0, size - max_bytes)
            handle.seek(start)
            payload = handle.read()
    except OSError:
        return []
    lines = payload.splitlines()
    if start and lines:
        lines = lines[1:]  # the window began mid-line
    return lines


def _walk_jsonl(root: Path, facts: dict | None = None) -> list[Path]:
    """Every `.jsonl` under `root`, without asking the OS about each one.

    `Path.rglob` works out dir-vs-file by stat'ing, and the caller's `is_file()`
    stat'ed again: over the store the qoder family shares that was 4,263
    `os.stat` calls and 0.254 s for 4,262 files, paid once per listing and by
    two listings per rebuild (the IDE's own and `qoderwake`'s view of the same
    directory). `os.scandir` carries the type in the same directory read that
    produced the name, which is 0.106 s and no stat. Symlinks are followed and
    an unreadable directory is passed over, both as `rglob` does: one locked
    project directory must not empty the whole list.

    `facts`, when given, collects `str(path) -> (mtime, size)` from the same
    directory entries. That is the point of the hand-rolled walk: the listing
    then asks 4,261 files for their version four times over (the id peek, the
    meta peek, the canonical ranking and the fragment scan's newest-first
    order), and a stat that the directory read already answered costs nothing.
    """
    out: list[Path] = []
    stack = [root]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=True):
                    stack.append(Path(entry.path))
                elif entry.name.lower().endswith(".jsonl") and entry.is_file(follow_symlinks=True):
                    path = Path(entry.path)
                    if facts is not None:
                        try:
                            est = entry.stat()
                        except OSError:
                            est = None
                        if est is not None:
                            facts[str(path)] = (est.st_mtime, est.st_size)
                    out.append(path)
            except OSError:
                continue
    return out


def _mtime_iso(stamp: float) -> str | None:
    """Last resort dating: the filesystem, when the store recorded nothing."""
    if not stamp:
        return None
    return _iso(datetime.fromtimestamp(stamp, tz=timezone.utc))


def _record_stamp(rows: list[dict]) -> str | None:
    """Newest `timestamp` any record in `rows` carries."""
    stamps = [iso for row in rows if (iso := _iso(row.get("timestamp")))]
    return max(stamps) if stamps else None


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


_SUMMARY_REQ = re.compile(r"Primary Request[^:\uFF1A]*[:\uFF1A]\s*(.{4,160})")


def _summary_title(text: str) -> str:
    """Compacted sessions open with <conversation_history_summary>; the user's
    real intent survives in its Primary Request line."""
    m = _SUMMARY_REQ.search(text)
    if m:
        frag = m.group(1).strip().strip("*").strip()
        if frag:
            return frag[:80]
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("<", "Summary")):
            return line[:80]
    return ""


# Sessions whose transcript holds zero real user messages: internal tool loops
# (spawned browser/automation sub-agents). Products never list them as
# conversations, so the cockpit drops them from the listing too (still loadable
# by id for debugging).
_TOOLLOOP_TITLE = "工具循环会话（无用户消息）"

# (path, mtime, size) -> the eight fields a peek derives, or () for "no rows".
# A roll is append-only, so a version key is enough: the head, the tail scan and
# the derived title cannot change without the size or the mtime changing too.
# This is what makes the 20s cache rebuild cheap instead of re-reading 800 lines
# per file: measured, the jsonl family alone spent 3.9s of an 11s build.
_PEEK_CACHE: dict[tuple[str, float, int], tuple] = {}

# (path, mtime, size) -> the session id that file's own records report. Same
# version key and the same argument as _PEEK_CACHE, and it is the difference
# between four qoder-family stores *sharing* one 4,261-file store and each of
# them re-reading the head of all 4,261 files on every 20s rebuild: measured, the
# uncached id peek cost 2.7s of an 11.3s poll and 8,995 of its ~9,000 opens.
_ID_CACHE: dict[tuple[str, float, int], str] = {}

# (path, mtime, size) -> "this roll opens with a session_meta/add_user_message
# row", i.e. it is one turn of a fragmented chat rather than a conversation.
# Same version key again; without it every store that shares the qoder store
# re-reads the head of all 2,302 canonical files per poll to ask a question the
# first store already answered.
_FRAG_HEAD_CACHE: dict[tuple[str, float, int], bool] = {}

# store -> {fragment text: the (path, mtime, size) that was carrying it}. A text
# is only skipped by a later scan while that exact version is still on disk: the
# proof is checked with one stat per remembered text, never by re-reading them.
_PROVEN_ABSORBED_TEXTS: dict[str, dict] = {}

# store -> {path: ((mtime, size), the fragment texts this version of the file was
# read for and does not contain)}. `proven` above remembers what a scan *found*;
# this remembers what it did not, which is the half that a live store pays for:
# a turn the store genuinely does not carry is proven absent only by reading up
# to the scan's byte budget, and while another session is being written that
# budget is re-spent on every 20 s rebuild - 50,000 JSON rows of it on this
# machine's qoder store, for a dozen fragments whose answer never changes
# (spec Round 55).
_ABSORB_ABSENT_TEXTS: dict[str, dict] = {}

# store -> {session id: (the versions of the files the answer was read from and
# the date the listing carried, the answer)}. The Needs-input probe reads a window
# of every listed row on every poll -- 144 MB a rebuild on this machine's stores --
# and a row's answer can only change when one of those versions does, which is the
# same rule `_PEEK_CACHE` and `_ABSORB_ABSENT_TEXTS` are built on. The listing date
# is part of the key because the probe declines when it outranks the turn it found.
_NEEDS_REPLY_CACHE: dict[str, dict] = {}

# ~/.qoder-cn (and ~/.qoder) is SHARED by the whole qoder family: the IDE's own
# chats live under <project>/transcript/ or in plain <project> dirs, while
# qoderwake team-groups/workers and qoderwork workspaces each create top-level
# project dirs named after the product. One listing must not mix families —
# the wake/work transcripts belong to their own CLI entries.
_FAMILY_MARKERS = ("qoderwake", "qoderwork")

#: `_family_of_path` runs once per listed session per rebuild and resolved the
#: store root on every one of those calls: 4,640 resolutions of eight distinct
#: roots, each a round of `stat` calls, in the measured 70,386-stat rebuild.
_RESOLVED_ROOTS: dict[str, Path | None] = {}


def _family_of_path(root: Path, path: str) -> str | None:
    """Which qoder family a transcript belongs to, from the store dir name."""
    rkey = str(root)
    if rkey not in _RESOLVED_ROOTS:
        try:
            _RESOLVED_ROOTS[rkey] = Path(root).resolve()
        except OSError:
            _RESOLVED_ROOTS[rkey] = None
    resolved = _RESOLVED_ROOTS[rkey]
    if resolved is None:
        return None
    try:
        rel = Path(path).resolve().relative_to(resolved)
    except (ValueError, OSError):
        return None
    for part in rel.parts:
        for family in _FAMILY_MARKERS:
            if family in part:
                return family
    return None


# Cache of absorbed add_user_message fragments per store, keyed by the store
# root and invalidated by the newest file mtime, so repeated dashboard loads do
# not rescan every real session just to de-duplicate a handful of turn fragments.
_QODER_ABSORB_CACHE: dict = {}
_ABSORB_SCAN_CAP_BYTES = 60_000_000

#: The workspace-model anchor answers one question about one session by reading
#: every sibling in the store, so opening the same session twice paid that scan
#: twice -- measured 2026-09-20 on this machine's qoder-ide store: **6,650 files
#: and 78,781 rows parsed for a single `load()`**, on a session whose own file is
#: 0.1 MiB.
#:
#: The facts are therefore cached **per sibling group**, keyed by the newest mtime
#: inside that group, not per store: a store-wide stamp is useless here because
#: the store is being written while the cockpit reads it (the session the reader
#: is watching grows every second), and measuring that showed a store-wide cache
#: hit nothing on 3 of 4 sessions. Fine-grained, the repeat cost is the number of
#: files that actually changed -- usually one -- and each cached entry is what the
#: scan's own loop would have produced, so no answer is computed differently.
#: Same mechanism and reasoning as `_QODER_ABSORB_CACHE` above.
_ANCHOR_FACTS: dict = {}

#: The ai-stats file telemetry, indexed once per stats-tree change rather than
#: re-read for every detail page. Keyed by the store directory; the value is the
#: (path, size, mtime) signature the index was built from and the map itself.
_TELE_INDEX: dict[str, tuple] = {}


def _tele_line(line: str, index: dict[str, Counter[str]]) -> None:
    """Fold one telemetry row into the index.

    A row credits its ``filePath`` to every session named in its ``lineDetails``,
    **once each**: asked about one session at a time, the per-session scan this
    replaces matched the first detail belonging to that session and stopped, so a
    row listing the same session twice counts once. Collapsing that to "the first
    session in the list" would quietly stop counting the others.
    """
    try:
        row = json.loads(line)
    except ValueError:
        return
    fp = row.get("filePath")
    if not isinstance(fp, str) or not fp.strip():
        return
    sids = {
        str(ld["sessionId"])
        for ld in row.get("lineDetails") or []
        if isinstance(ld, dict) and ld.get("sessionId")
    }
    for sid in sids:
        index.setdefault(sid, Counter())[fp] += 1


def _newest_mtime(paths) -> float:
    """The newest mtime among `paths`, or -1 if none can be stat'ed.

    A file that vanished cannot be stat'ed, and the scan that consults it skips
    it too -- but the stamp must not silently survive a deletion, so a failure
    reports the sentinel that no successful walk can produce.
    """
    newest = -1.0
    for group in paths:
        for p in group:
            try:
                m = p.stat().st_mtime
            except OSError:
                return -2.0
            newest = max(newest, m)
    return newest


def _parse_iso_local(iso):
    """Parse an ISO timestamp (qoder mixes +00:00 strings); None on failure."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def _row_shape(row: dict) -> str:
    """A reportable name for a row the parser did not read.

    Refined by the store's own sub-type where it has one, because `attachment`
    on its own would say nothing useful: 9 of the 12 attachment kinds this
    machine's stores write are injected context (task_reminder 3136 rows,
    skill_listing 1460, agent_listing_delta 1286, ...) and 3 name files.
    Reporting them together is how a real one gets ignored.
    """
    base = str(row.get("type") or "<no-type>")
    if base != "attachment":
        return base
    att = row.get("attachment")
    if isinstance(att, dict) and att.get("type"):
        return f"attachment/{att.get('type')}"
    return "attachment/<no-subtype>"


#: Row types that legitimately carry no turn - bookkeeping and side-channel
#: records the parser reads or ignores on purpose. Anything reaching the
#: no-role fall-through outside this list becomes a visible `unhandled_row:`
#: fact, because "the store started writing a shape nobody has seen" must not be
#: indistinguishable from "nothing happened".
#:
#: The list is the set the live store actually produced, over 131 sampled
#: family sessions (spec Round 41), with the count of sessions in which each
#: appeared: runtime-config 54, last-prompt 49, workspace-directories 47,
#: active-leaf 46, attachment 43, worktree-state 35, ai-title 24, session_meta
#: 18, progress 14, system 8, session-meta 7, resend-fork-notice 7, custom-title
#: 4. Two of those are deliberately NOT here - `attachment` and
#: `resend-fork-notice` - because both look like they carry something a session
#: depended on, and `_load_paths` reads them for exactly that reason: the
#: attachment kinds that name files become touched paths, and a fork record
#: marks the two turns it is about. Anything of theirs that cannot be placed
#: says so.
ROLELESS_ROW_TYPES: frozenset[str] = frozenset({
    "session_meta",
    "session-meta",
    "runtime-config",
    "last-prompt",
    "workspace-directories",
    "active-leaf",
    "worktree-state",
    "ai-title",
    "custom-title",
    "progress",
    "system",
    "summary",
    "isCompactSummary",
    # Injected context, named by the store's own sub-type: rows saying which
    # skills/agents exist, hook output, queue and goal reminders. Counted on
    # 2026-09-19 as task_reminder 3136, skill_listing 1460, agent_listing_delta
    # 1286, hook_output 190, queued_command 87, hook_non_blocking_error 55,
    # critical_system_reminder 37, goal_state 18, relevant_memories 11 rows.
    # The three attachment kinds that name files are NOT here - `_load_paths`
    # reads those, and an attachment sub-type nobody has seen still gets
    # reported.
    "attachment/task_reminder",
    "attachment/skill_listing",
    "attachment/agent_listing_delta",
    "attachment/hook_output",
    "attachment/queued_command",
    "attachment/hook_non_blocking_error",
    "attachment/critical_system_reminder",
    "attachment/goal_state",
    "attachment/relevant_memories",
    "attachment/hook_error_during_execution",
    # Found by asking the whole store instead of a sample (spec Round 48): the
    # 131-session sample behind the list above had never met these three.
    # Counted 2026-09-20 over every jsonl this store holds - 4,214 files,
    # 328,530 rows - as invoked_skills 2, hook_system_message 2, auto_mode_exit 1
    # rows. Two are excused for what they are, not for being rare:
    # `auto_mode_exit` is an empty `{"type": ...}` marker, and
    # `hook_system_message` is a hook printing at the user, i.e. the same
    # side-channel family as `hook_output` above. `invoked_skills` is the one
    # carrying real content (skill names plus their SKILL.md text): it is
    # excused because a skill file the harness loaded is not a file the session
    # worked on, so it must not join the touched-paths list - the fact that no
    # surface shows "which skills ran" is recorded in docs/limitations.md
    # instead of being quietly dropped here.
    "attachment/invoked_skills",
    "attachment/hook_system_message",
    "attachment/auto_mode_exit",
})

#: Attachment sub-types whose payload names files the product models as touched.
#: The three `plan_*` kinds were found by reporting attachments per sub-type:
#: as one `attachment` blob they were invisible, and all three carry
#: `planFilePath`.
#:
#: `plan_mode_reentry` is the fourth, and it was missed: the full sweep met it on
#: 2026-09-20 and it was falling through as unread while its siblings were read.
#: Its payload is `{"type": "plan_mode_reentry", "planFilePath": ...}` - the same
#: key `_attachment_files` already lifts - so excluding it under-reported the
#: files a planning session touched.
FILE_BEARING_ATTACHMENTS = frozenset({
    "file",
    "edited_text_file",
    "post_compact_restored_files",
    "plan_file_reference",
    "plan_mode",
    "plan_mode_exit",
    "plan_mode_reentry",
})

#: A store's own status word -> the end state it proves. Only the two stores
#: that keep such a column/file reach for this, and only terminal words are
#: listed: `working` and `idle` describe liveness, `archived` describes
#: bookkeeping, and none of them says how the turn ended. Mapping a non-terminal
#: word is the mistake this table exists to keep out - a recorded fact is worth
#: reporting, an unrelated one is not allowed to become "clean".
STORE_END_STATES = {
    "completed": "clean",
    "done": "clean",
    "finished": "clean",
    "error": "error",
    "failed": "error",
}


class JsonlSessionParser(Parser):
    """Shared reader for Claude Code / CodeBuddy / compatible JSONL dialects."""

    cli = "jsonl"
    projects_dirname: str = ""  # ".claude" / ".codebuddy"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (home() / self.projects_dirname / "projects")
        # sid -> every file that reports it, filled by list_sessions().
        self._index: dict[str, list[Path]] = {}
        # str(path) -> (mtime, size) from the last walk of this store. Replaced
        # wholesale by every base `_iter_jsonl()` call, so it never outlives the
        # pass that filled it; a parser whose `_iter_jsonl` is overridden simply
        # has none, and every reader below falls back to a stat.
        self._dirfacts: dict[str, tuple[float, int]] = {}
        # sid -> the file this listing read that row's own dialogue from. Only
        # the listings that walk the store themselves (`_CodebuddyHybridParser`)
        # fill it, because a store that lists through `list_sessions` already has
        # `_index`. Deliberately separate from `_index`: that map is what `load()`
        # merges, so adding a row's sub-agent transcripts to it here would change
        # a transcript to answer a column.
        self._listed_files: dict[str, list[Path]] = {}
        # sid -> the timestamp the listing reported for that row. The tail probe
        # compares it against the newest turn its window could see: when the
        # listing knows about something newer, a turn exists that the window did
        # not reach, and the probe's answer is about the wrong end of the file.
        self._listing_stamp: dict[str, str | None] = {}
        # The rows the last `list_sessions()` did not list, with the reason on
        # each one. See `_split_toolloops`.
        self._hidden: list[SessionMeta] = []

    def _split_toolloops(self, metas: list[SessionMeta]) -> list[SessionMeta]:
        """Keep the conversations; park the tool loops on ``self._hidden``.

        The rule is unchanged from the one this file has always applied — a row
        whose title is the tool-loop sentinel is not a conversation, exactly as
        the product's own UI does not list them. What is new is the receipt:
        dropping 107 rows from a store of 2,638 was invisible, and "invisible"
        and "lost" look the same from the outside (spec Round 54).

        Call it *after* any family filtering: four entries read two shared
        stores, and a stash made before the split would carry the same rows for
        each of them.
        """
        keep: list[SessionMeta] = []
        hidden: list[SessionMeta] = []
        for m in metas:
            if m.title == _TOOLLOOP_TITLE:
                m.hidden_reason = "tool-loop"
                hidden.append(m)
            else:
                keep.append(m)
        self._hidden = hidden
        return keep

    def hidden_sessions(self) -> list[SessionMeta]:
        """What the last ``list_sessions()`` of this parser did not list."""
        return list(self._hidden)

    def available(self) -> bool:
        return self.root.is_dir()

    # -- discovery ----------------------------------------------------------

    def _iter_jsonl(self) -> list[Path]:
        if not self.available():
            return []
        facts: dict[str, tuple[float, int]] = {}
        found = sorted(_walk_jsonl(self.root, facts))
        self._dirfacts = facts
        return found

    def _version(self, path: Path) -> tuple[float, int] | None:
        """(mtime, size) for a transcript, from the directory read that named it.

        A listing pass asks 4,261 files for their version four times over -- the
        id peek, the meta peek, the canonical ranking and the fragment scan's
        newest-first order -- which was 40,000 of the 114,728 `os.stat` calls in
        one measured rebuild. `os.scandir` had both numbers in the entry it
        already returned, so the walk carries them. None means no answer: a file
        the walk did not see that a stat cannot describe either, which a caller
        must not mistake for version (0, 0).
        """
        hit = self._dirfacts.get(str(path))
        if hit is not None:
            return hit
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_mtime, st.st_size)

    def _group_files(self, paths: list[Path], sid: str) -> list[Path]:
        """Rank a session's files: canonical transcript first, companions after."""

        def rank(path: Path) -> tuple[int, int]:
            score = 0
            if path.stem == sid:
                score = 3
            elif path.parent.name == sid or path.name == "session.jsonl":
                score = 2
            elif path.name.startswith("agent-"):
                score = 1  # sub-agent transcript, part of the session but not its head
            ver = self._version(path)
            return (score, ver[1] if ver else 0)

        return sorted(paths, key=rank, reverse=True)

    def list_sessions(self) -> list[SessionMeta]:
        """One entry per session, even when the store splits it over many files.

        Reading the id out of each record and then emitting per-file entries made
        a session with sub-agent transcripts appear several times, and left
        `load()` looking for a file name that does not exist. Grouping first fixes
        both, and keeps `source_path` pointing at the canonical transcript.
        """
        groups: dict[str, list[Path]] = {}
        for path in self._iter_jsonl():
            sid = self._peek_id(path)
            if sid:
                groups.setdefault(sid, []).append(path)
        self._index = groups
        self._listing_stamp = {}

        metas: list[SessionMeta] = []
        for sid, paths in groups.items():
            meta = self._peek(self._group_files(paths, sid)[0])
            if meta is not None:
                meta.session_id = sid
                self._listing_stamp[sid] = meta.updated_at
                metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def _peek_id(self, path: Path) -> str:
        """Session id as the store reports it, falling back to the file stem."""
        ver = self._version(path)
        key = (str(path), ver[0], ver[1]) if ver else None
        if key is not None:
            hit = _ID_CACHE.get(key)
            if hit is not None:
                return hit
        sid = ""
        for row in read_jsonl(path, limit=10):
            value = row.get("sessionId") or row.get("session_id")
            if value:
                sid = str(value)
                break
        if not sid:
            sid = path.stem
        if key is not None:
            if len(_ID_CACHE) > 8192:  # a long-lived process, a growing store
                _ID_CACHE.clear()
            _ID_CACHE[key] = sid
        return sid

    def _origin(self) -> str | None:
        """Store directory (e.g. .qoderwork vs .qoderworkcn) = account scope."""
        name = self.root.parent.name
        return name if name.startswith(".") else None

    def _peek(self, path: Path) -> SessionMeta | None:
        """Scan the head of a roll for identity + the first real title.

        limit=800 because compaction/quest transcripts bury the first real turn
        under hundreds of tool-hint/meta rows (measured: a 13 MB compacted roll
        keeps its summary at line 487).
        """
        ver = self._version(path)
        key = (str(path), ver[0], ver[1]) if ver else (str(path), 0.0, 0)
        hit = _PEEK_CACHE.get(key)
        if hit is not None:
            if not hit:
                return None  # the file was empty when it was read
            return SessionMeta(
                cli=self.cli,
                session_id=hit[0],
                title=hit[1],
                cwd=hit[2],
                started_at=hit[3],
                updated_at=hit[4],
                source_path=str(path),
                origin=self._origin(),
            )
        rows = read_jsonl(path, limit=800)
        if not rows:
            if len(_PEEK_CACHE) > 8192:  # a long-lived process, a growing store
                _PEEK_CACHE.clear()
            _PEEK_CACHE[key] = ()
            return None
        cwd = ""
        session_id = path.stem
        title = ""
        ai_title = ""
        started = updated = None
        for r in rows:
            cwd = cwd or (r.get("cwd") or "")
            session_id = r.get("sessionId") or session_id
            # Official title rows (workbuddy/codebuddy write an AI title as a
            # dedicated row, usually near the top). Track them separately: they
            # outrank the first-user-message guess even when found AFTER the
            # first user turn, so the scan must not break on the user turn.
            if r.get("type") == "ai-title" and r.get("aiTitle"):
                ai_title = ai_title or str(r["aiTitle"])[:80]
            if r.get("type") == "summary" and r.get("summary"):
                title = title or str(r["summary"])[:80]
            role, text, _raw, _tools = self._row_content(r)
            if role == "user" and text and not self.is_noise(text):
                started = _iso(r.get("timestamp")) or started
                if not title:
                    if text.startswith("<conversation_history_summary"):
                        title = _summary_title(text)
                    else:
                        title = text[:80]
                if ai_title:
                    break
        tail = _tail_rows(path)
        # The official ai-title row is appended asynchronously near the END of
        # the roll, after the conversation; a head-only scan misses it. It is
        # the product's own title, so it outranks the first-user-message guess.
        for r in tail:
            if r.get("type") == "ai-title" and r.get("aiTitle"):
                ai_title = str(r["aiTitle"])[:80]
                break
        title = ai_title or title
        updated = _record_stamp(rows) or _record_stamp(tail)
        if updated is None:
            # Only a store that records no timestamps at all may be dated by its
            # filesystem - and then the date means "copied", not "last turn".
            try:
                updated = _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
            except OSError:
                updated = None
        if not title:
            # No user text and no official title row: a pure tool loop (usually
            # a spawned browser/automation sub-agent). Say so honestly instead of
            # leaking a bare short id that looks like a parsing failure.
            title = _TOOLLOOP_TITLE
        meta = SessionMeta(
            cli=self.cli,
            session_id=session_id,
            title=title,
            cwd=cwd,
            started_at=started,
            updated_at=updated,
            source_path=str(path),
            origin=self._origin(),
        )
        if len(_PEEK_CACHE) > 8192:
            _PEEK_CACHE.clear()
        _PEEK_CACHE[key] = (session_id, title, cwd, started, updated)
        return meta

    def load(self, session_id: str) -> RawSession | None:
        paths = self._resolve_group(session_id)
        if not paths:
            return None
        return self._load_paths(paths, session_id)

    def _raw_entries(self, paths: list[Path]) -> list[dict] | None:
        """One verbatim entry per transcript file (byte-faithful)."""
        out: list[dict] = []
        for path in paths:
            if not path.is_file():
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            try:
                rel = str(path.resolve().relative_to(self.root.resolve()))
            except (ValueError, OSError):
                rel = str(path)
            out.append(file_entry(path, raw, rel))
        return out or None

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """Every file that makes the session, byte-faithful. JSONL stores keep
        their conversation exactly as the vendor appended it — tool calls,
        system rows and future fields included; nothing re-derived.
        """
        return self._raw_entries(self._resolve_group(session_id))

    def peek_needs_reply(self, session_id: str) -> bool | None:
        """Tail-scan the session's transcripts: is the last real turn a user one?

        Runs for every row of the session list, so it stays cheap by
        construction: the canonical transcript plus at most ``_PROBE_FILES``
        companions, one bounded window each, and no ``_resolve_group`` -- that can
        fall back to a full-store rglob scan, which run once per listed session
        stalls the whole listing.

        Four ways that first version left rows unanswered or wrong on real stores,
        each measured before being fixed (spec Round 56):

        * **The window was too small to contain a turn.** Sixteen kilobytes of a
          qoder transcript is one to three records, because its non-dialogue rows
          -- attachments, history snapshots -- run to tens of kilobytes each. The
          newest turn sat just above that: this machine's ``qoder-ide`` store
          answered 1,350 of its 2,287 rows and answers 2,279 now. The window is
          64 KB, and a line is tested for a role token before it is parsed, so the
          larger read does not drag a larger decode with it.
        * **A store whose listing walks the files itself filled no ``_index``**,
          which was the only place the probe looked: 172 rows (156 ``workbuddy``,
          16 ``codebuddy``) declined without reading a byte, while the listing had
          opened the file they live in seconds earlier. That listing now records it.
        * **An entry that delegates its transcripts** -- the wake entries read the
          shared qoder store through another parser, which holds both the index
          and the merge -- asked itself instead. It asks the owner now, which is
          where ``qoderwake-cn`` went from answering none of its 11 rows to 9.
        * **A split session can be read from the wrong file**, once the probe looks
          beyond one transcript: a session's companions are usually sub-agent
          transcripts, and a sub-agent file ends on the task it was handed, not on
          the conversation's last word. Reading the companions before the
          canonical transcript answers 9 of this machine's 172 split rows as a false
          "needs input" (measured against their own detail page), so the order is
          fixed below and pinned by a test.

        Two things keep the wider read affordable and honest: the answer is
        memoised against the version of every file it was read from (a warm rebuild
        reads 0.1 MB instead of 144), and a row declines when the listing dates it
        after the turn found -- the file's end is then not its newest content, and
        "not waiting" would be the one answer worth losing to avoid. What stays
        unanswered stays "unknown", which the cockpit renders as its own state;
        ``docs/limitations.md`` carries the row counts and the price of the rest.
        """
        paths = self._index.get(session_id) or self._listed_files.get(session_id)
        if not paths:
            return None
        # The canonical transcript first, for the reason measured in the docstring
        # above; companions only as a fallback, newest version first, because a
        # conversation continued across files keeps its last words in the newest
        # continuation.
        ranked = self._group_files(list(paths), session_id)
        head, rest = ranked[0], ranked[1:]
        rest.sort(key=lambda p: self._version(p) or (-1.0, 0), reverse=True)
        consulted = [head, *rest[: self._PROBE_FILES]]
        listed = self._listing_stamp.get(session_id)
        # One answer per file version, not per poll: this runs for every row of the
        # list every 30 s, and 64 KB across 2,491 rows is 144 MB of reading a
        # rebuild. The key is the version of each file the answer is read from plus
        # the date the listing reported, because that date is part of what the
        # answer means (see the guard below).
        key = (
            tuple((str(path), self._version(path)) for path in consulted),
            listed,
            # The window and the file cap are inputs to the answer, not just
            # settings: a parser that tunes either must re-derive, not inherit.
            (self._PROBE_BYTES, self._PROBE_FILES),
        )
        memo = _NEEDS_REPLY_CACHE.setdefault(str(self.root), {})
        hit = memo.get(session_id)
        if hit is not None and hit[0] == key:
            return hit[1]
        answer: bool | None = None
        seen_stamp: str | None = None
        for path in consulted:
            for raw in reversed(_tail_lines(path, self._PROBE_BYTES)):
                # A byte test before a parse: the records that fill a qoder tail
                # are 30-100 KB blobs with no dialogue in them, and decoding one
                # to learn it is not a turn costs more than the read. Nothing is
                # missed by the test -- a line with no role token in it cannot be
                # a turn this parser would accept either -- and a miss answers
                # "unknown", never "answered".
                if b'"user"' not in raw and b'"assistant"' not in raw:
                    continue
                try:
                    row = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                role, text, _raw, _tools = self._row_content(row)
                if role in ("user", "assistant") and text and not self.is_noise(text):
                    answer = role == "user"
                    seen_stamp = _iso(row.get("timestamp"))
                    break
            if answer is not None:
                break
        if answer is None:
            verdict = None
        elif answer is False and listed and seen_stamp and listed > seen_stamp:
            # The listing dated this row from the session's own records, so a date
            # newer than the turn just found means the file's end is not its newest
            # content and the answer is about the wrong part of the conversation.
            # That is applied to the "not waiting" answer only, and the asymmetry is
            # deliberate: an "unknown" beside a conversation that is waiting costs a
            # highlight, while "answered" beside one that is waiting hides the work
            # the column exists to surface. Measured on this machine's stores it
            # silences 8 rows, 7 of them answers the window had right, and is the
            # reason the column has no known disagreement with a detail page.
            verdict = None
        else:
            verdict = answer
        if len(memo) > 8192:  # a long-lived process, a growing store
            memo.clear()
        memo[session_id] = (key, verdict)
        return verdict

    #: How far above the end of a transcript a row is answered from, and how many
    #: of the session's files that read covers. Both are cost decisions stated as
    #: bytes per listed row: 64 KB is where this machine's qoder stores keep their
    #: newest turn -- at 16 KB the family answered 1,383 of its 2,491 rows, at
    #: 64 KB it answers 2,477 -- and the reads stay bounded per file, memoised by
    #: version so a poll does not re-read what has not changed.
    _PROBE_BYTES = 65_536
    _PROBE_FILES = 3

    def _resolve_group(self, session_id: str) -> list[Path]:
        """All files that make up one session; cheap and storage-layout agnostic."""
        if session_id.endswith(".jsonl"):  # a caller passed a path
            one = Path(session_id)
            return [one] if one.exists() else []
        cached = self._index.get(session_id)
        if cached:
            return self._group_files(cached, session_id)
        # Index is empty when load() is called without a prior list_sessions()
        # (e.g. the cockpit detail endpoint creates a fresh parser per request).
        # Populate it so sub-agent files (agent-*.jsonl) are reachable by the
        # session id recorded inside their records, not just by filename.
        if not self._index:
            self.list_sessions()
            cached = self._index.get(session_id)
            if cached:
                return self._group_files(cached, session_id)
        found = [
            p for p in self._iter_jsonl() if p.stem == session_id or p.parent.name == session_id
        ]
        if found:
            return self._group_files(found, session_id)
        return []

    # -- extraction ---------------------------------------------------------

    def _apply_log_models(self, raw: RawSession) -> int:
        """Attribute serving models + measured durations from session logs.

        Segment rows carry ``{ts, type:model.response.completed, data:{model,
        input_tokens, output_tokens}}`` (token fields are server-side zero
        placeholders — never attributed) and ``{ts, type:turn.finished,
        data:{duration_ms}}`` (server-measured turn cost — attributed as
        ``dur_ms``, outranking timestamp derivation). Both fill assistant
        turns lacking them (nearest within ±120s).
        Test/fixture trees (root outside the real home) never touch disk.
        Shared by the work-CLI mixin and the IDE parser: both stores keep
        ``<store>/logs/sessions/<sid>/segments/*.jsonl``.
        """
        try:
            rooted = self.root.resolve().is_relative_to(home().resolve())
        except (OSError, ValueError):
            return 0
        if not rooted or not self.projects_dirname:
            return 0
        # Walk up from root to the hidden-store dir.
        store = None
        rp = self.root
        for _ in range(4):
            if rp.name == self.projects_dirname:
                store = rp
                break
            rp = rp.parent
        if store is None:
            return 0
        logs = store / "logs" / "sessions"
        if not logs.is_dir():
            return 0
        sid = raw.meta.session_id
        # Task sessions append .session.execution to the transcript name;
        # the log dir uses the bare task id.
        sid_bare = sid.split(".session.execution")[0]
        # Turn-precise attribution: transcript promptId == log turn_id, so
        # each log turn (model + duration) maps to the transcript turn that
        # shares its id; timestamp proximity (±120s) is only the fallback.
        # Build at->promptId from the transcript files backing this session.
        at_to_prompt: dict[str, str] = {}
        try:
            for path in self._resolve_group(sid):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    pid = row.get("promptId")
                    ts = row.get("timestamp")
                    if pid and ts:
                        iso = ts_to_iso(ts)
                        if iso:
                            at_to_prompt.setdefault(iso, str(pid))
        except (OSError, ValueError):
            pass
        events: list[tuple] = []
        durs: list[tuple] = []
        turn_ids: dict[str, list[tuple]] = {}
        seen: set[str] = set()
        for key in ({sid, sid_bare}):
            for seg in sorted(logs.rglob(f"{key}/segments/*.jsonl")):
                if str(seg) in seen:
                    continue
                seen.add(str(seg))
                try:
                    text = seg.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    data = row.get("data") or {}
                    tid = str(row.get("turn_id") or "")
                    if row.get("type") == "model.response.completed":
                        model = str(data.get("model") or "").strip()
                        at = _parse_iso_local(row.get("ts"))
                        if model and at is not None:
                            events.append((at, model))
                            if tid:
                                turn_ids.setdefault(tid, []).append((at, model, None))
                    elif row.get("type") == "turn.finished":
                        dur = data.get("duration_ms")
                        at = _parse_iso_local(row.get("ts"))
                        if isinstance(dur, int) and dur > 0 and at is not None:
                            durs.append((at, dur))
                            if tid:
                                turn_ids.setdefault(tid, []).append((at, None, dur))
        hit = 0
        if events or turn_ids:
            for m in raw.messages:
                if m.role != "assistant" or m.model or not m.at:
                    continue
                # Exact first: same turn id on both sides.
                pid = at_to_prompt.get(m.at or "")
                exact = None
                if pid:
                    for _at, model, _ in turn_ids.get(pid, []):
                        if model:
                            exact = model
                            break
                if exact is not None:
                    m.model = exact
                    hit += 1
                    continue
                mat = _parse_iso_local(m.at)
                if mat is None:
                    continue
                best = None
                best_d = 120.0
                for at, model in events:
                    d = abs((mat - at).total_seconds())
                    if d < best_d:
                        best, best_d = model, d
                if best is not None:
                    m.model = best
                    hit += 1
        if durs:
            for m in raw.messages:
                if m.role != "assistant" or m.dur_ms is not None or not m.at:
                    continue
                mat = _parse_iso_local(m.at)
                if mat is None:
                    continue
                best = None
                best_d = 120.0
                for at, dur in durs:
                    d = abs((mat - at).total_seconds())
                    if d < best_d:
                        best, best_d = dur, d
                if best is not None:
                    m.dur_ms = best
                    hit += 1
        return hit

    def _row_content(self, row: dict) -> tuple[str, str, str, list[dict]]:
        """Return (role, plain_text, raw_text, tool_blocks) for one JSONL row."""
        rtype = row.get("type")
        if rtype not in (None, "message", "user", "assistant"):
            return "", "", "", []
        inner = row.get("message") if isinstance(row.get("message"), dict) else {}
        role = row.get("role") or inner.get("role") or ""
        content = row.get("content") if row.get("content") is not None else inner.get("content")
        text, tools = as_text_blocks(content)
        return role, self.clean_text(text), text, tools

    @staticmethod
    def _row_billing(row: dict) -> tuple[str, dict]:
        """(model, token counters) recorded on one row, dialect-tolerant.

        CodeBuddy/WorkBuddy hang them under ``providerData`` (``model`` plus
        ``rawUsage``/``usage``); the Claude-Code dialect puts them on the inner
        ``message`` object. Only assistant turns carry billing.
        """
        pd = row.get("providerData")
        src = pd if isinstance(pd, dict) else {}
        inner = row.get("message") if isinstance(row.get("message"), dict) else {}
        model = src.get("model") or inner.get("model") or ""
        usage = src.get("rawUsage") or src.get("usage") or inner.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        details = usage.get("completion_tokens_details")
        details = details if isinstance(details, dict) else {}
        pdetails = usage.get("prompt_tokens_details")
        pdetails = pdetails if isinstance(pdetails, dict) else {}
        tokens = {
            "in": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "out": usage.get("completion_tokens") or usage.get("output_tokens"),
            "reasoning": details.get("reasoning_tokens"),
            "cache_read": pdetails.get("cached_tokens") or usage.get("cache_read_input_tokens"),
        }
        return str(model) if model else "", {k: int(v) for k, v in tokens.items() if v is not None}

    def _tool_name_input(self, block: dict) -> tuple[str, dict]:
        name = block.get("name") or block.get("tool") or block.get("toolName") or "tool"
        tool_input = block.get("input")
        if not isinstance(tool_input, dict):
            inner = block.get("state") or {}
            tool_input = inner.get("input") if isinstance(inner, dict) else {}
        return str(name), (tool_input if isinstance(tool_input, dict) else {})

    @staticmethod
    def _subagent_label(path: Path) -> str | None:
        """Which sub-agent a transcript belongs to, or None for the main file.

        Sub-agent rolls live under ``<session>/subagents/`` and are named
        ``agent-<hash>.jsonl`` (codebuddy/workbuddy); the main conversation is the
        sibling ``<session>.jsonl``. Tagging lets the UI show sub-agent work under
        the parent instead of a flat interleaved dump.
        """
        if path.parent.name == "subagents" or path.name.startswith("agent-"):
            return path.stem
        return None

    def _load_paths(self, paths: list[Path], session_id: str) -> RawSession:
        """Merge a session's files: main transcript first, companions after."""
        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        todos: list[TodoItem] = []
        tool_failures: list[str] = []
        cwd = ""
        title = ""
        started = None
        newest_at: str | None = None
        newest_mtime = 0.0
        seen_ids: set[tuple[str, str]] = set()
        # callId -> claimed tool name, so result rows join back to the call.
        pending_calls: dict[str, str] = {}
        # Billing that rides on non-message rows (workbuddy puts usage on
        # function_call rows, which never become Messages): settled onto the
        # next assistant turn, same as the codex token_count flow.
        pending_billing: dict = {}
        # Exact attribution: usage rows and message rows share
        # providerData.conversationRequestId — key billing by it so out-of-order
        # files can't misattribute one request's spend to another.
        billing_by_req: dict[str, dict] = {}
        # Session-serving model from runtime-config rows (IDE family); turns
        # without their own billing inherit it.
        runtime_model: str = ""
        # Row-level provider signals that never surface as turns: compacted
        # summaries, errors, and the agent surface (cli vs IDE).
        row_errors: list[str] = []
        unhandled: Counter[str] = Counter()
        # In-file forks: `editedUserItemId` of every fork record seen, the turn
        # each row id belongs to, and whether a re-send claim is still waiting
        # for the turn the store wrote directly after its record.
        fork_targets: list[str] = []
        turn_by_row_id: dict[str, Message] = {}
        pending_resent = False
        # Forks the transcript can only show one end of — counted so the gap is
        # a fact on the session instead of a silent absence.
        fork_target_missing = 0
        compacted_summaries = 0
        agent_surfaces: set[str] = set()
        # Session-level pre-scan: does ANY row carry real text? A session of
        # pure tool_use/tool_result rows is an internal tool loop — its tool
        # rows stay dropped so load() is honestly empty. Byte-capped.
        _has_text = False
        _scanned = 0
        for _path in paths:
            if _has_text or _scanned > 1_000_000:
                break
            try:
                _raw = _path.read_bytes()[:200_000] if _path.is_file() else b""
            except OSError:
                continue
            _scanned += len(_raw)
            for _row in read_jsonl(_path, limit=400):
                _role, _text, _, _ = self._row_content(_row)
                if _role in ("user", "assistant") and _text and not self.is_noise(_text):
                    _has_text = True
                    break

        for path in paths:
            try:
                newest_mtime = max(newest_mtime, path.stat().st_mtime)
            except OSError:
                continue
            sub_label = self._subagent_label(path)
            for row in read_jsonl(path):
                rtype = row.get("type")
                if rtype == "summary":
                    continue
                cwd = cwd or (row.get("cwd") or "")
                at = _iso(row.get("timestamp"))
                started = started or at
                if at and (newest_at is None or at > newest_at):
                    newest_at = at
                self._collect_row_signals(row, agent_surfaces, row_errors)
                if rtype == "runtime-config" and isinstance(row.get("model"), str) and row["model"]:
                    # The IDE records the serving model per session here
                    # (e.g. qmodel_38max); transcripts carry no per-turn
                    # billing, so assistant turns inherit this below.
                    runtime_model = row["model"]
                if row.get("isCompacted") or row.get("isSummary"):
                    # A turn the product already replaced with a summary: count
                    # it, count its text only if there is real prose in it.
                    compacted_summaries += 1

                if rtype == "reasoning":
                    # The model's own thinking. rawContent carries the text;
                    # content is usually empty.
                    rtext, rraw = self._reasoning_text(row)
                    if rtext:
                        model = self._row_billing(row)[0]
                        messages.append(
                            self.msg(
                                "assistant",
                                f"[思考] {rraw}",
                                text=f"[思考] {rtext}",
                                at=at,
                                model=model or None,
                                subagent=sub_label,
                            )
                        )
                    continue
                if rtype == "function_call":
                    name = str(row.get("name") or "tool")
                    call_id = str(row.get("callId") or "")
                    if call_id:
                        pending_calls[call_id] = name
                    tools[name] += 1
                    args = self._tool_args(row)
                    for p in self.extract_paths(args):
                        files[p] += 1
                    _m, _t = self._row_billing(row)
                    if _t.get("in") is not None or _t.get("out") is not None:
                        # usage rows often come in runs (tool-loop tails):
                        # accumulate, the next assistant turn takes the sum.
                        acc = pending_billing.get("pending") or {}
                        for k in ("in", "out", "reasoning", "cache_read"):
                            v = _t.get(k)
                            if isinstance(v, int):
                                acc[k] = acc.get(k, 0) + v
                        pending_billing["pending"] = acc
                        # Exact key when present: providerData.conversationRequestId
                        # is shared by the usage row and its request's turns.
                        pd = row.get("providerData")
                        req = pd.get("conversationRequestId") if isinstance(pd, dict) else None
                        if isinstance(req, str) and req:
                            prev = billing_by_req.get(req) or {}
                            for k in ("in", "out", "reasoning", "cache_read"):
                                v = _t.get(k)
                                if isinstance(v, int):
                                    prev[k] = prev.get(k, 0) + v
                            billing_by_req[req] = prev
                    continue
                if rtype == "function_call_result":
                    name = str(row.get("name") or "")
                    call_id = str(row.get("callId") or "")
                    if not name and call_id:
                        name = pending_calls.get(call_id, "tool")
                    if name:
                        status = str(row.get("status") or "")
                        out = row.get("output")
                        otext = ""
                        if isinstance(out, dict):
                            otext = str(out.get("text") or "")[:300]
                        elif isinstance(out, str):
                            otext = out[:300]
                        if status and status != "completed":
                            tool_failures.append(f"{name}:{status}")
                            disp = f"[工具{name} {status}] {self.clean_text(otext)[:300]}"
                            messages.append(
                                self.msg(
                                    "assistant",
                                    f"[工具{name} {status}] {otext}",
                                    text=disp,
                                    at=at,
                                    subagent=sub_label,
                                )
                            )
                        elif _has_text:
                            # Successful calls are visible collapsible cards in
                            # the product timeline — dropping them hides the
                            # work. One folded line; the full output stays in
                            # raw_text for the 原文 view.
                            mark = "✓" if status == "completed" else ""
                            disp = f"[工具{name} {mark}]".strip()
                            summary = self.clean_text(otext)[:160]
                            if summary:
                                disp += f" {summary}"
                            messages.append(
                                self.msg(
                                    "assistant",
                                    otext,
                                    text=disp,
                                    at=at,
                                    subagent=sub_label,
                                )
                            )
                    continue
                if rtype == "file-history-snapshot":
                    for fp in self._snapshot_files(row):
                        files[fp] += 1
                    continue

                if rtype == "resend-fork-notice":
                    # The store's own record of an in-file fork: the user edited
                    # a turn they had already sent and sent the new text again.
                    # The row carries no turn of its own - only the id of the
                    # turn that was edited - so both ends are settled once the
                    # turns exist: the named turn below, the re-sent one at the
                    # next turn this loop appends.
                    eid = row.get("editedUserItemId")
                    fork_targets.append(eid if isinstance(eid, str) else "")
                    pending_resent = True
                    continue

                if rtype == "attachment" and isinstance(row.get("attachment"), dict):
                    # Several attachment kinds name a file the session opened or
                    # edited. The product models that as a touched path, so they
                    # are read here instead of being reported unread; injected
                    # context kinds (skills, hooks, reminders) carry no turn and
                    # fall through to the shape report, where their sub-type is
                    # what decides whether that is expected.
                    att = row["attachment"]
                    if str(att.get("type") or "") in FILE_BEARING_ATTACHMENTS:
                        for fp in self._attachment_files(att):
                            files[fp] += 1
                        continue

                role, text, raw_text, tool_blocks = self._row_content(row)
                if not role:
                    # Nothing matched this row and it carries no turn, so it
                    # ends up unread here. For bookkeeping rows that is correct;
                    # for a shape the parser has never seen it is invisible from
                    # outside the process, which is how a store shipping a new
                    # record type reads as "nothing happened". Count them all
                    # first; ROLELESS_ROW_TYPES is what the live store showed.
                    unhandled[_row_shape(row)] += 1
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
                    # IDE task transcripts carry tool calls as their own rows
                    # (the product timeline shows them as collapsible cards).
                    # Fold each into a one-line [工具 name] turn — unless the
                    # WHOLE session has no real text at all, in which case it
                    # is an internal tool loop that stays honestly empty
                    # (see test_qoder_tool_loop_hidden_but_loadable).
                    if isinstance(tb, dict) and tb.get("type") == "tool_use" and _has_text:
                        arg = ""
                        if isinstance(tool_input, dict):
                            for k in ("file_path", "path", "command", "pattern", "query"):
                                v = tool_input.get(k)
                                if isinstance(v, str) and v.strip():
                                    arg = f" {v.strip()[:80]}"
                                    break
                        tool_line = f"[工具 {name}]{arg}"
                        model_tb, _ = self._row_billing(row)
                        messages.append(
                            self.msg(
                                "assistant",
                                json.dumps(tb, ensure_ascii=False),
                                text=tool_line,
                                at=at,
                                model=model_tb or runtime_model or None,
                                subagent=sub_label,
                            )
                        )
                if text and not self.is_noise(text):
                    # A re-send claim reaches only the turn written directly
                    # after the fork record. Any turn takes it or clears it, so
                    # a filtered or duplicated row cannot leave the flag live
                    # for an unrelated turn further down the file.
                    _resent_here = pending_resent
                    pending_resent = False
                    key = (role, text)
                    if key in seen_ids:
                        continue  # the same turn mirrored into a companion file
                    seen_ids.add(key)
                    # System-context reminders are real turns but never
                    # titles — the product shows the ai-title / first real
                    # prompt instead.
                    if (
                        role == "user"
                        and not title
                        and not text.lstrip().startswith("<system-reminder")
                    ):
                        title = text[:80]
                    model, tokens = self._row_billing(row)
                    if not model:
                        model = runtime_model
                    if (
                        role == "assistant"
                        and tokens.get("in") is None
                        and tokens.get("out") is None
                    ):
                        # Exact first: same conversationRequestId as a usage row.
                        pd = row.get("providerData")
                        req = pd.get("conversationRequestId") if isinstance(pd, dict) else None
                        exact = billing_by_req.get(req) if isinstance(req, str) else None
                        pend = exact or pending_billing.get("pending")
                        if pend:
                            # The usage row bills the whole request: the text
                            # turn takes it, and so do the run-up thinking
                            # turns of the same request that have none yet.
                            tokens = {
                                **tokens,
                                **{k: v for k, v in pend.items() if tokens.get(k) is None},
                            }
                            for m in reversed(messages):
                                if m.role != "assistant":
                                    break
                                if m.tokens_in is None and m.tokens_out is None:
                                    m.tokens_in = pend.get("in")
                                    m.tokens_out = pend.get("out")
                                    reasoning = pend.get("reasoning")
                                    if reasoning is not None and m.tokens_reasoning is None:
                                        m.tokens_reasoning = reasoning
                                elif m.text and not m.text.startswith("[思考]"):
                                    break
                            if not exact:
                                pending_billing.pop("pending", None)
                    messages.append(
                        self.msg(
                            role,
                            raw_text,
                            text=text,
                            at=at,
                            model=model or None,
                            tokens_in=tokens.get("in"),
                            tokens_out=tokens.get("out"),
                            tokens_reasoning=tokens.get("reasoning"),
                            subagent=sub_label,
                        )
                    )
                    if role == "user":
                        _turn = messages[-1]
                        _rid = row.get("id")
                        if isinstance(_rid, str) and _rid:
                            # Fork records name turns by this id; keep the
                            # first copy, since a companion file mirroring the
                            # same row must not split the link across objects.
                            turn_by_row_id.setdefault(_rid, _turn)
                        if _resent_here:
                            _turn.resent = True

        if len({m.at for m in messages if m.at}) > 1 and all(m.at for m in messages):
            messages.sort(key=lambda m: m.at or "")  # merge companions chronologically

        # Second pass after the chronological sort: thinking turns stranded by
        # cross-file disorder take the model of the nearest settled turn —
        # but NEVER its tokens. Cross-turn token inheritance misattributes
        # one request's spend to another; None stays honest absence.
        # Only [思考] turns qualify — text turns without billing mean the store
        # recorded no usage row for that request (honest absence).
        settled: list = []
        for m in messages:
            if m.role == "assistant" and m.model:
                settled.append(m)
        if settled:
            for m in messages:
                if (
                    m.role == "assistant"
                    and m.tokens_in is None
                    and m.tokens_out is None
                    and (m.text or "").startswith("[思考]")
                    and m.at
                    and not m.model
                ):
                    nxt = next((s for s in settled if (s.at or "") >= (m.at or "")), None)
                    if nxt is None:
                        continue
                    m.model = nxt.model

        # Cloud-billing overlay (user-supplied): qoder-family per-turn billing
        # lives in the cloud; after the user exports it to
        # ~/.agenthandoff/cloud-usage/<sid>.json it is attributed here by
        # timestamp (±2s). Absent file = zero impact.
        self.apply_cloud_overlay(messages, session_id)

        # Session-dominant model backfill: tool-result rows carry no
        # providerData, but they execute inside this session's calls — label
        # them with the session's own dominant model so every row shows the
        # serving model. Tokens stay absent (honest).
        dom = Counter(m.model for m in messages if m.role == "assistant" and m.model)
        if dom:
            top, ntop = dom.most_common(1)[0]
            if ntop >= 2:
                for m in messages:
                    if m.role == "assistant" and not m.model:
                        m.model = top

        # The other end of every fork: the turn the store named is the
        # abandoned copy. It is a separate flag from `resent` because both hold
        # of the same turn in most real sessions — editing the newest message
        # again is how the product is used. A name matching no kept user turn
        # is reported rather than dropped: the link is real, its target is not
        # in this file.
        for _tid in fork_targets:
            _t = turn_by_row_id.get(_tid) if _tid else None
            if _t is None:
                fork_target_missing += 1
                continue
            _t.superseded = True

        notes: list[str] = [f"tool_failed:{f}" for f in tool_failures[:20]]
        if agent_surfaces:
            notes.append(f"surface:{'/'.join(sorted(agent_surfaces))}")
        if compacted_summaries:
            notes.append(f"compacted_turns:{compacted_summaries}")
        notes.extend(f"row_error:{e}" for e in row_errors[:5])
        # Biggest signal first, same cap as row_error: a session that meets a
        # thousand unread shapes should say so without burying the row payload.
        _fresh = [(k, n) for k, n in unhandled.items() if k not in ROLELESS_ROW_TYPES]
        for _kind, _n in sorted(_fresh, key=lambda kv: (-kv[1], kv[0]))[:5]:
            notes.append(f"unhandled_row:{_kind}={_n}")
        if len(_fresh) > 5:
            notes.append(f"unhandled_row_kinds:{len(_fresh)}")
        if fork_target_missing:
            notes.append(f"fork_target_missing:{fork_target_missing}")
        meta = SessionMeta(
            cli=self.cli,
            session_id=session_id,
            title=title or session_id,
            cwd=cwd,
            started_at=started,
            updated_at=newest_at or _mtime_iso(newest_mtime),
            source_path=str(paths[0]),
            origin=self._origin(),
            notes=notes,
        )
        return self.build_raw(
            meta, messages, todos, files, tools, self._proven_interruption(session_id)
        )

    def _proven_interruption(self, session_id: str) -> Interruption | None:
        """An ending this store recorded, as evidence. None when it recorded none.

        `Interruption.kind` no longer defaults to "clean" (spec Round 39), so a
        store that does keep a terminal status would otherwise be reported as
        unknown - trading one wrong answer for another. Each class that reads
        such a column or file overrides this.
        """
        return None

    @staticmethod
    def _collect_row_signals(row: dict, surfaces: set[str], errors: list[str]) -> None:
        """providerData side-channels that never become turns.

        ``agent`` (cli vs IDE) names the product surface; ``error`` records
        why a turn died (e.g. Interrupted by user); usage doubles
        (rawUsage + usage) are left to _row_billing.
        """
        pd = row.get("providerData")
        if not isinstance(pd, dict):
            return
        agent = pd.get("agent")
        if isinstance(agent, str) and agent.strip():
            surfaces.add(agent.strip())
        err = pd.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or "").strip()
            if msg and msg not in errors:
                errors.append(msg[:160])

    @staticmethod
    def _reasoning_text(row: dict) -> tuple[str, str]:
        """The model's thinking: rawContent[].text (content is usually empty).

        Returns (cleaned, raw): the 2000-char cap and cleaning apply to the
        display form only; the raw form stays whole for the 原文 view.
        """
        for key in ("rawContent", "content"):
            blocks = row.get(key) or []
            if not isinstance(blocks, list):
                continue
            parts = [
                str(b.get("text") or "")
                for b in blocks
                if isinstance(b, dict) and b.get("type") in ("reasoning_text", "text")
            ]
            raw = "\n".join(p for p in parts if p).strip()
            if raw:
                return raw[:2000], raw
        return "", ""

    @staticmethod
    def _tool_args(row: dict) -> dict:
        """function_call carries input as arguments (dict or JSON string)."""
        args = row.get("arguments")
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                return parsed if isinstance(parsed, dict) else {}
            except ValueError:
                return {}
        return row.get("input") if isinstance(row.get("input"), dict) else {}

    @staticmethod
    def _snapshot_files(row: dict) -> list[str]:
        """trackedFileBackups maps a path to its backup — keys ARE the paths."""
        snap = row.get("snapshot") or {}
        backups = snap.get("trackedFileBackups") or {}
        return [str(k) for k in backups if isinstance(k, str) and k.strip()]

    @staticmethod
    def _attachment_files(att: dict) -> list[str]:
        """Paths a file-bearing attachment names outright.

        `file` and `edited_text_file` carry `filename`, the `plan_*` kinds carry
        `planFilePath`, and `post_compact_restored_files` carries a list with
        `filePath` per entry. The store spells the path out, so nothing is
        guessed here - a value the product would have to infer is a value it
        should not report.
        """
        out: list[str] = []
        for key in ("filename", "planFilePath"):
            direct = att.get(key)
            if isinstance(direct, str) and direct.strip():
                out.append(direct.strip())
        entries = att.get("files")
        if isinstance(entries, str):
            # Some rolls serialise the list as JSON text instead of an array.
            try:
                entries = json.loads(entries)
            except (ValueError, TypeError):
                entries = []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("filePath"), str):
                    fp = entry["filePath"].strip()
                    if fp:
                        out.append(fp)
        return out

    def usage(self, session_id: str) -> dict | None:
        """Per-model token accounting aggregated from the turns themselves.

        Works for any dialect that records per-turn billing (codebuddy's
        providerData.rawUsage, the Claude-Code message.usage). Returns the same
        shape the dedicated stores (zcode/codex) produce, with latency columns
        left null because flat JSONL stores time nothing that fine.
        """
        raw = self.load(session_id)
        if raw is None:
            return None
        agg: dict[str, dict] = {}
        for m in raw.messages:
            if not m.model or (m.tokens_in is None and m.tokens_out is None):
                continue
            a = agg.setdefault(
                m.model,
                {"calls": 0, "tokens_in": 0, "tokens_out": 0, "reasoning": 0},
            )
            a["calls"] += 1
            a["tokens_in"] += m.tokens_in or 0
            a["tokens_out"] += m.tokens_out or 0
            a["reasoning"] += m.tokens_reasoning or 0
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
                    "cache_write": 0,
                    "cache_read": 0,
                    "avg_ttft_ms": None,
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


class ClaudeCodeParser(JsonlSessionParser):
    cli = "claude"
    projects_dirname = ".claude"


class _CodebuddyHybridParser(JsonlSessionParser):
    """Codebuddy uses two layouts under ``<root>/<project>/``:

    1. **Flat**: ``<project>/<session-id>.jsonl`` — standalone session.
    2. **Nested**: ``<project>/<session-dir>/subagents/agent-*.jsonl`` —
       sub-agent transcripts belonging to the directory (the real session).

    The directory name in layout 2 is the session ID; sub-agent files carry
    an internal ``sessionId`` that is runtime context (the parent that
    spawned them), not the file's own identity.  Grouping by the embedded
    ID split one directory's agents into separate "sessions" and merged
    unrelated directories — both wrong.
    """

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        metas: list[SessionMeta] = []
        seen: set[str] = set()
        self._listed_files = {}
        self._listing_stamp = {}

        # Layout 2: session dirs with subagents/ children.
        for subagents_dir in sorted(self.root.rglob("subagents")):
            session_dir = subagents_dir.parent
            sid = session_dir.name
            if sid in seen or not sid.replace("-", "").isalnum():
                continue
            seen.add(sid)
            agent_files = sorted(subagents_dir.glob("*.jsonl"))
            if not agent_files:
                continue
            # The main transcript usually also exists as a flat file next to the
            # session dir; it carries the real user dialogue (sub-agent files are
            # side work), so let it lead the metadata scan.
            flat = session_dir.parent / (sid + ".jsonl")
            scan_files = [flat] + agent_files if flat.is_file() else agent_files
            if scan_files:
                # The tail probe needs to know which file carries this row's
                # dialogue, and `_index` is not the place to say it: that map
                # feeds `load()`, and handing it `[flat] + agent_files` would add
                # the sub-agent transcripts to a transcript that today does not
                # carry them. So a listing of this shape keeps its own record.
                self._listed_files[sid] = [scan_files[0]]
            meta = self._cb_peek_dir(sid, agent_files, scan_files)
            if meta:
                metas.append(meta)

        # Layout 1: flat .jsonl files that are NOT inside a session dir's
        # subagents/ — each is its own standalone session.
        for path in sorted(self.root.rglob("*.jsonl")):
            if not path.is_file():
                continue
            # Skip files inside subagents/ — those belong to layout 2.
            if path.parent.name == "subagents":
                continue
            sid = self._peek_id(path)
            if sid in seen:
                continue
            seen.add(sid)
            meta = self._peek(path)
            if meta is not None:
                meta.session_id = sid
                self._listed_files[sid] = [path]
                metas.append(meta)

        # Agents (codebuddy background jobs) carry the official session name in
        # jobs/<shortid>/state.json; the sessionId field links the job to the
        # conversation (it may differ from the job's own short id).
        for m in metas:
            self._listing_stamp[m.session_id] = m.updated_at
        titles = self._job_titles()
        for m in metas:
            jt = titles.get(m.session_id)
            if jt:
                m.title = jt
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        # Pure tool loops (edit-and-resend orphans: zero real user messages)
        # are not conversations — the product UI never lists them, so neither
        # do we. Still loadable by id for debugging, and kept on the shelf so
        # a surface can say how many it did not show (`hidden_sessions`).
        return self._split_toolloops(metas)

    def _job_dirs(self) -> list:
        """Candidate jobs/ dirs: own store plus the codebuddy shared one.

        WorkBuddy reuses CodeBuddy's job runtime (same shortId dir names,
        same state.json schema); its own tree has no jobs/ dir. Resolved
        from the store dirname (not root.parent: tests may aim root at the
        store itself instead of its projects/ child).
        """
        from agent_handoff.locations import home

        dirs = []
        if self.projects_dirname:
            # Walk up from root until the hidden-store dir is found.
            rp = self.root
            for _ in range(4):
                if rp.name == self.projects_dirname:
                    dirs.append(rp / "jobs")
                    break
                rp = rp.parent
        shared = home() / ".codebuddy" / "jobs"
        if all(shared != d for d in dirs):
            dirs.append(shared)
        return [d for d in dirs if d.is_dir()]

    def _job_titles(self) -> dict[str, str]:
        """sessionId -> official agent name from ``jobs/*/state.json``.

        These are the titles codebuddy's own UI shows for its agents — the
        highest-priority source, above ai-title rows and first-user fallback.
        """
        out: dict[str, str] = {}
        for jobs_dir in self._job_dirs():
            for state in jobs_dir.glob("*/state.json"):
                try:
                    d = json.loads(state.read_text(encoding="utf-8", errors="replace"))
                except (OSError, json.JSONDecodeError):
                    continue
                sid = d.get("sessionId")
                name = d.get("name")
                if sid and name:
                    out[sid] = str(name)[:80]
        return out

    def _job_states(self) -> dict[str, str]:
        """sessionId -> live job state from ``jobs/*/state.json``.

        The product UI shows background agents as working/idle; the state
        field is that same signal. Cached per call site (see peek_status).
        """
        out: dict[str, str] = {}
        for jobs_dir in self._job_dirs():
            for state in jobs_dir.glob("*/state.json"):
                try:
                    d = json.loads(state.read_text(encoding="utf-8", errors="replace"))
                except (OSError, json.JSONDecodeError):
                    continue
                sid = d.get("sessionId")
                st = d.get("state")
                if sid and isinstance(st, str) and st:
                    out[sid] = st
        return out

    def _store_status_word(self, session_id: str) -> str | None:
        """The word this store keeps for the session, in its own vocabulary."""
        try:
            return self._job_states().get(session_id)
        except OSError:
            return None

    def peek_status(self, session_id: str) -> str | None:
        """The store's status word, translated into the product's end-state words.

        Only an ending is reported: a job that is `working` or `idle`, or a row
        that is merely `archived`, has not said how the turn ended, so those
        report nothing rather than a borrowed word. That keeps the badge on the
        row and the label on the detail page the same string, which is what lets
        `scripts/probe_audit.py` compare the two at all.
        """
        word = self._store_status_word(session_id)
        if word is None:
            return None
        return STORE_END_STATES.get(str(word))

    def _proven_interruption(self, session_id: str) -> Interruption | None:
        """The recorded ending, as evidence.

        Both subclasses that keep a status column or file reach here through
        `_store_status_word`, so the row badge and the handoff answer from one
        record. Without it, `Interruption` no longer defaulting to "clean"
        (spec Round 39) would have hidden an ending these two stores really do
        store.
        """
        kind = self.peek_status(session_id)
        if kind is None:
            return None
        word = self._store_status_word(session_id)
        return Interruption(kind=kind, detail=f"{self.cli} recorded status={word}")

    def _cb_peek_dir(
        self, sid: str, agent_files: list[Path], scan_files: list[Path] | None = None
    ) -> SessionMeta | None:
        """Cheap metadata scan for one session dir.

        ``scan_files`` defaults to the sub-agent files; callers pass the flat
        main transcript first when one exists so its user dialogue wins the title.
        """
        cwd = ""
        title = ""
        ai_title = ""
        started = updated = None
        stamp_files: list[Path] = []
        for path in scan_files or agent_files:
            stamp_files.append(path)
            for r in read_jsonl(path, limit=800):
                cwd = cwd or (r.get("cwd") or "")
                if r.get("type") == "ai-title" and r.get("aiTitle"):
                    ai_title = ai_title or str(r["aiTitle"])[:80]
                if r.get("type") == "summary" and r.get("summary"):
                    title = title or str(r["summary"])[:80]
                role, text, _raw, _tools = self._row_content(r)
                if role == "user" and text and not self.is_noise(text):
                    if not title:
                        if text.startswith("<conversation_history_summary"):
                            title = _summary_title(text)
                        else:
                            title = text[:80]
                    started = started or _iso(r.get("timestamp"))
                stamp = _iso(r.get("timestamp"))
                if stamp and (updated is None or stamp > updated):
                    updated = stamp
            if title and cwd:
                break
        title = ai_title or title
        if updated is None:
            try:
                mt = max(p.stat().st_mtime for p in (stamp_files or agent_files))
                updated = _iso(datetime.fromtimestamp(mt, tz=timezone.utc))
            except (OSError, ValueError):
                pass
        head = (scan_files or agent_files)[0] if (scan_files or agent_files) else agent_files[0]
        return SessionMeta(
            cli=self.cli,
            session_id=sid,
            title=title or _TOOLLOOP_TITLE,
            cwd=cwd,
            started_at=started,
            updated_at=updated,
            source_path=str(head),
            origin=self._origin(),
        )

    def load(self, session_id: str) -> RawSession | None:
        if session_id.endswith(".jsonl"):
            one = Path(session_id)
            return self._load_paths([one], session_id) if one.exists() else None

        # Layout 2: session dir with subagents/. The flat main transcript (the
        # real user dialogue) sits next to the dir and MUST be loaded together
        # with the sub-agent files — reading only the sub-agents silently drops
        # the whole main conversation.
        session_dir = self._find_session_dir(session_id)
        if session_dir is not None:
            paths: list[Path] = []
            flat = session_dir.parent / (session_id + ".jsonl")
            if flat.is_file():
                paths.append(flat)  # canonical head: ranks above agent-* files
            subagents_dir = session_dir / "subagents"
            if subagents_dir.is_dir():
                paths.extend(sorted(subagents_dir.glob("*.jsonl")))
            if paths:
                raw = self._load_paths(paths, session_id)
                if raw is not None:
                    jt = self._job_titles().get(session_id)
                    if jt:
                        raw.meta.title = jt
                    self._apply_db_overlay(raw)
                return raw

        # Layout 1: flat file — fall back to the base class resolver.
        raw = super().load(session_id)
        if raw is not None:
            jt = self._job_titles().get(session_id)
            if jt:
                raw.meta.title = jt
            self._apply_db_overlay(raw)
        return raw

    def _apply_db_overlay(self, raw) -> None:
        """Copy store-level overlays (kind/expert) onto a loaded session.

        list_sessions() applies _db_kinds/_db_experts; load() builds a fresh
        meta from the transcript, so re-apply here to keep both views honest.
        Base implementation is a no-op; WorkbuddyParser overrides it.
        """

    def _find_session_dir(self, session_id: str) -> Path | None:
        """Locate a session dir by name under any project."""
        if not self.available():
            return None
        for subagents_dir in self.root.rglob("subagents"):
            if subagents_dir.parent.name == session_id:
                return subagents_dir.parent
        return None

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """Verbatim files exactly as load() reads them: the flat main
        transcript plus every sub-agent roll of the session dir."""
        if session_id.endswith(".jsonl"):
            one = Path(session_id)
            return self._raw_entries([one]) if one.is_file() else None
        session_dir = self._find_session_dir(session_id)
        if session_dir is not None:
            paths: list[Path] = []
            flat = session_dir.parent / (session_id + ".jsonl")
            if flat.is_file():
                paths.append(flat)
            sub = session_dir / "subagents"
            if sub.is_dir():
                paths.extend(sorted(sub.glob("*.jsonl")))
            if paths:
                return self._raw_entries(paths)
        return super().raw_archive(session_id)


class CodebuddyParser(_CodebuddyHybridParser):
    cli = "codebuddy"
    projects_dirname = ".codebuddy"


class CodebuddyCnParser(JsonlSessionParser):
    """CodeBuddy CN edition — same layout under ~/.codebuddycn."""

    cli = "codebuddy-cn"
    projects_dirname = ".codebuddycn"


class WorkbuddyParser(_CodebuddyHybridParser):
    """WorkBuddy — codebuddy-shaped transcripts plus a SQLite title index.

    Layout mirrors codebuddy (flat ``<sid>.jsonl`` + ``<sid>/subagents/``), so
    the hybrid reader is reused as-is. What codebuddy lacks is a durable title:
    workbuddy keeps one in ``~/.workbuddy/workbuddy.db`` (``sessions.title`` /
    ``custom_title``), so list_sessions() overlays it after the heuristic scan.
    Titles like ``@long-text:"..."`` are truncated quote markers and are reduced
    to the quoted head.
    """

    cli = "workbuddy"
    projects_dirname = ".workbuddy"

    def usage(self, session_id: str) -> dict | None:
        """Turn-aggregated usage plus the store's own quota/credit ledger.

        workbuddy.db.session_usage records per-session context spend (used/size)
        and per-model credit costs (credit_json: model-hash -> credits). Both are
        attached under `credits`/`quota` — that is the billing layer the raw
        turns cannot express.
        """
        result = super().usage(session_id)
        try:
            import json as _json
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if db.is_file():
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                try:
                    row = conn.execute(
                        "SELECT used, size, credit_json FROM session_usage WHERE session_id=?",
                        (session_id,),
                    ).fetchone()
                finally:
                    conn.close()
                if row:
                    used, size, credit_raw = row
                    if result is None:
                        result = {
                            "models": [],
                            "totals": {"calls": 0, "tokens_in": 0, "tokens_out": 0},
                        }
                    result["quota"] = {"used": used, "size": size}
                    if credit_raw:
                        with contextlib.suppress(ValueError):
                            result["credits"] = _json.loads(credit_raw)
        except Exception:  # ledger missing — turn-based usage still stands
            pass
        return result

    def list_sessions(self) -> list[SessionMeta]:
        metas = super().list_sessions()  # already carries jsonl ai-title rows
        db = self._db_titles()
        kinds = self._db_kinds()
        autos = self._db_automations()
        for m in metas:
            # The AI-generated title written into the transcript is the title
            # the product shows; the db sessions.title (often the raw first
            # prompt) only fills gaps.
            if not m.title or m.title == m.session_id or len(m.title) <= 8:
                t = db.get(m.session_id)
                if t:
                    m.title = t
            # Session kind as the product organises it: playground /
            # background-automation / working-source (working/craft/design/
            # coding) / plain craft. Drives the cockpit kind badge.
            k = kinds.get(m.session_id)
            if k:
                m.task_type = k
            # Automation归属: automation_runs.runs_json[].conversationId
            # links background runs to their automation (tts/LUFS/每日检查…).
            # Recorded as a note; the server groups by it so no session is
            # 主-less in the cockpit.
            a = autos.get(m.session_id)
            if a:
                m.notes = [*m.notes, f"automation:{a}"]
        experts = self._db_experts()
        for m in metas:
            ex = experts.get(m.session_id)
            if ex:
                m.expert_name, m.expert_avatar = ex
        return metas

    def _apply_db_overlay(self, raw) -> None:
        # Same overlays list_sessions() applies: kind + expert always win
        # (store-level facts); the db title only fills gaps so the
        # transcript's own ai-title / job-title keeps priority.
        sid = raw.meta.session_id
        experts = self._db_experts()
        ex = experts.get(sid)
        if ex:
            raw.meta.expert_name, raw.meta.expert_avatar = ex
        k = self._db_kinds().get(sid)
        if k:
            raw.meta.task_type = k
        if not raw.meta.title or raw.meta.title == sid or len(raw.meta.title) <= 8:
            t = self._db_titles().get(sid)
            if t:
                raw.meta.title = t
        # Per-request credit attribution: session_usage.credit_json maps
        # conversationRequestId -> credits (100% key match verified). The
        # request id rides on providerData but _load_paths drops it, so
        # re-resolve: credit goes to the first assistant text turn at/after
        # the request's own timestamp. Tokens stay absent (honest).
        credits = self._db_credits(sid)
        if credits:
            self._attribute_credits(raw, sid, credits)

    def _db_credits(self, session_id: str) -> dict[str, float]:
        """session request credits from workbuddy.db.session_usage."""
        try:
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if not db.is_file():
                return {}
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
            try:
                row = conn.execute(
                    "SELECT credit_json FROM session_usage WHERE session_id=?",
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
            if not row or not row[0]:
                return {}
            data = json.loads(row[0])
            return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}
        except (OSError, ValueError):
            return {}

    def _attribute_credits(self, raw, session_id: str, credits: dict[str, float]) -> None:
        """Attach per-request credits to turns by request timestamp.

        Transcript rows carry providerData.conversationRequestId (= the
        credit key) plus their own timestamp; match each credit to the
        earliest assistant text turn at/after its request time. One credit
        lands on exactly one turn (no splitting, no double count).
        """
        try:
            paths = self._resolve_group(session_id)
        except (OSError, ValueError):
            return
        # request id -> earliest row timestamp
        req_at: dict[str, object] = {}
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                pd = row.get("providerData")
                if not isinstance(pd, dict):
                    continue
                req = pd.get("conversationRequestId")
                ts = row.get("timestamp")
                if req and ts and req not in req_at:
                    at = ts_to_iso(ts)
                    if at:
                        req_at[str(req)] = at
        if not req_at:
            return
        for req, amount in credits.items():
            at = req_at.get(req)
            if at is None:
                continue
            # Prefer the request's text turn (the billable answer); fall
            # back to the earliest tool row when the request has no text.
            best = None
            for m in raw.messages:
                if m.role != "assistant" or m.credits is not None or not m.at:
                    continue
                if m.text.startswith("[思考]") or m.text.startswith("[工具"):
                    continue
                if m.at >= at and (best is None or m.at < best.at):
                    best = m
            if best is None:
                for m in raw.messages:
                    if m.role != "assistant" or m.credits is not None or not m.at:
                        continue
                    if m.text.startswith("[思考]"):
                        continue
                    if m.at >= at and (best is None or m.at < best.at):
                        best = m
            if best is not None:
                best.credits = amount

    def _db_experts(self) -> dict[str, tuple[str | None, str | None]]:
        """session_id -> (expert name, avatar URL) from assistant-display.

        ``~/.workbuddy/assistant-display/<sid>.json`` keeps timestamped
        snapshots; the latest resolved one is what the product shows.
        Avatar URLs point at the vendor's public CDN (display-only).
        """
        try:
            disp = home() / ".workbuddy" / "assistant-display"
            if not disp.is_dir():
                return {}
            out: dict[str, tuple[str | None, str | None]] = {}
            for path in disp.glob("*.json"):
                sid = path.stem
                try:
                    d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                except (OSError, ValueError):
                    continue
                snaps = d.get("snapshots") if isinstance(d, dict) else None
                if not isinstance(snaps, list) or not snaps:
                    continue
                last = None
                for s in snaps:
                    if not isinstance(s, dict):
                        continue
                    ad = s.get("assistantDisplay")
                    if isinstance(ad, dict) and ad.get("resolution") != "provisional":
                        last = ad
                if last is None:
                    for s in reversed(snaps):
                        if isinstance(s, dict) and isinstance(s.get("assistantDisplay"), dict):
                            last = s["assistantDisplay"]
                            break
                if not isinstance(last, dict):
                    continue
                name = last.get("name") or last.get("profession")
                avatar = last.get("avatarUrl")
                out[sid] = (
                    str(name)[:40] if isinstance(name, str) and name else None,
                    str(avatar)[:300] if isinstance(avatar, str) and avatar else None,
                )
            return out
        except OSError:
            return {}

    def _db_kinds(self) -> dict[str, str]:
        """session_id -> kind from workbuddy.db (read-only).

        Priority: playground > background-automation > source_mode >
        mode > none. Mirrors how the product separates playground tries,
        background runs and working modes.
        """
        try:
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if not db.is_file():
                return {}
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
            try:
                rows = conn.execute(
                    "SELECT id, mode, source_mode, is_playground, "
                    "is_background_automation, deleted_at FROM sessions"
                ).fetchall()
            finally:
                conn.close()
        except Exception:
            return {}
        out: dict[str, str] = {}
        for sid, mode, source, play, bg, deleted in rows:
            if deleted or not sid:
                continue
            kind = None
            if str(play) == "1":
                kind = "playground"
            elif str(bg) == "1":
                kind = "background"
            elif source and str(source).strip():
                kind = str(source).strip()
            elif mode and str(mode).strip():
                kind = str(mode).strip()
            if kind:
                out[str(sid)] = kind
        return out

    def _store_status_word(self, session_id: str) -> str | None:
        """workbuddy.db sessions.status (completed/archived/error/…).

        Same cost class as the title lookup; deleted rows report None. The
        shared `peek_status` translates the word, so the list only ever shows a
        recorded ending and the detail page treats the same column as evidence.
        """
        try:
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if not db.is_file():
                return None
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
            try:
                row = conn.execute(
                    "SELECT status FROM sessions WHERE id=? AND deleted_at IS NULL",
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
        except Exception:
            return None
        if not row or not row[0]:
            return None
        return str(row[0])

    def _db_automations(self) -> dict[str, str]:
        """session_id -> automation name from automation_runs (read-only).

        ``runs_json[].conversationId`` is the session id; the automation
        name (tts / LUFS / 每日检查…) is the parent a background session
        belongs to. NOTE: ``deleted_at`` carries timestamps on every row
        (not a live/dead flag), so it must NOT filter — status rides along
        in the note instead.
        """
        try:
            import json as _json
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if not db.is_file():
                return {}
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
            try:
                names = {}
                for aid, name, status in conn.execute(
                    "SELECT id, name, status FROM automations"
                ).fetchall():
                    label = str(name or "").strip()
                    if status and str(status).strip().upper() != "ACTIVE":
                        label = f"{label} [{status}]"
                    if aid and label:
                        names[str(aid)] = label
                runs = conn.execute(
                    "SELECT runs_json, automation_id FROM automation_runs"
                ).fetchall()
            finally:
                conn.close()
        except Exception:
            return {}
        out: dict[str, str] = {}
        for runs_json, aid in runs:
            name = names.get(str(aid or ""))
            if not name:
                continue
            try:
                items = _json.loads(runs_json or "[]")
            except ValueError:
                continue
            if not isinstance(items, list):
                continue
            for run in items:
                if not isinstance(run, dict):
                    continue
                cid = run.get("conversationId")
                if cid and str(cid) not in out:
                    out[str(cid)] = name
        return out

    def _db_titles(self) -> dict[str, str]:
        """session_id -> display title from workbuddy.db (read-only)."""
        try:
            import sqlite3

            db = home() / self.projects_dirname / "workbuddy.db"
            if not db.is_file():
                return {}
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT id, title, custom_title, deleted_at FROM sessions"
                ).fetchall()
            finally:
                conn.close()
            out: dict[str, str] = {}
            for sid, title, custom, deleted in rows:
                if deleted:
                    continue
                t = self._clean_title(custom or title)
                if sid and t:
                    out[str(sid)] = t
            return out
        except Exception:  # DB locked / schema drift — heuristic titles stand
            return {}

    @staticmethod
    def _clean_title(raw) -> str:
        if not raw:
            return ""
        t = str(raw).strip()
        # "@long-text:\"...\" <long_text_quote>..." is a truncation marker;
        # keep the quoted head so the list shows real content, not the wrapper.
        if t.startswith("@long-text:"):
            body = t.split(":", 1)[1].strip()
            if body.startswith('"'):
                end = body.find('"', 1)
                if end > 0:
                    body = body[1:end]
            t = body.split("<long_text_quote>")[0].strip()
        return t[:120]


class _QoderworkSharedMixin:
    """The work CLI also lands workspace sessions in the shared qoder store
    (~/.qoder/projects/<...qoderwork-workspace-...>); they belong to the work
    CLI entry, not to the IDE one. Overriding ``_iter_jsonl`` keeps listing
    and loading on the same file set.
    """

    shared_store = ".qoder"
    workspace_marker = "qoderwork-workspace"

    def _shared_root(self) -> Path | None:
        # ``self.root`` is either ``<home>/<hidden-store>/projects`` (production)
        # or the hidden-store dir itself (tests with an explicit root).
        candidates = (self.root.parent.parent, self.root.parent)
        for base in candidates:
            shared = base / self.shared_store / "projects"
            if shared.is_dir() and shared.resolve() != self.root.resolve():
                return shared
        return None

    def _iter_jsonl(self) -> list[Path]:
        paths = list(super()._iter_jsonl())
        shared = self._shared_root()
        if shared is not None:
            for p in shared.rglob("*.jsonl"):
                if self.workspace_marker in str(p):
                    paths.append(p)
        return sorted(set(paths))

    def execution_anchors(self, state_dir: Path | None = None) -> Counter[str]:
        """Task-execution traces the CLI never lists as sessions.

        ``~/.qodersec/state/*/*.session.execution.json`` records, per task,
        every path the agent touched (plus l1 lint findings). They carry no
        dialogue — only file anchors — so they supplement, never create,
        sessions. Read-only; lock files skipped.
        """
        from agent_handoff.locations import home

        out: Counter[str] = Counter()
        state = state_dir or home() / ".qodersec" / "state"
        if not state.is_dir():
            return out
        for path in state.rglob("*.session.execution.json"):
            if path.name.endswith(".lock"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            touched = data.get("touched_paths") or []
            if isinstance(touched, list):
                for p in touched:
                    if isinstance(p, str) and p.strip():
                        out[p] += 1
        return out

    def load(self, session_id: str) -> RawSession | None:
        """Transcript first, then the qodersec execution traces as file-only
        supplements: they carry no dialogue, so they merge into
        ``files_touched`` (never into messages) and are marked in notes.
        Fixture/test trees (root outside the real home) never merge: the
        evidence layer must measure the transcript alone."""
        raw = super().load(session_id)
        if raw is None:
            return None
        try:
            rooted = self.root.resolve().is_relative_to(home().resolve())
        except (OSError, ValueError):
            rooted = False
        if not rooted:
            return raw
        anchors = self.execution_anchors()
        if anchors:
            for p, n in anchors.items():
                raw.files_touched[p] = raw.files_touched.get(p, 0) + n
            raw.meta.notes = [*raw.meta.notes, f"qodersec_anchors:{len(anchors)}"]
        # Session-log model attribution: ~/.<store>/logs/sessions/*/<sid>/
        # segments/*.jsonl records model.response.completed per LLM call
        # (model + ts; token fields are zero placeholders server-side).
        # Attribute the serving model to nearby unattributed turns.
        n_applied = self._apply_log_models(raw)
        if n_applied:
            raw.meta.notes = [*raw.meta.notes, f"log_models:{n_applied}"]
        return raw

class QoderworkParser(_QoderworkSharedMixin, JsonlSessionParser):
    """Qoderwork — Claude-Code-style JSONL under ~/.qoderwork/projects."""

    cli = "qoderwork"
    projects_dirname = ".qoderwork"


class QoderworkCnParser(_QoderworkSharedMixin, JsonlSessionParser):
    """Qoderwork CN — a separate login (second account) under ~/.qoderworkcn.

    Variant directories of the same product are distinct account scopes:
    the user may run one account per variant (verified live: each carries
    its own .auth/machine_id). ``origin`` records which store a session
    came from so multi-account usage stays distinguishable.
    """

    cli = "qoderwork-cn"
    projects_dirname = ".qoderworkcn"
    shared_store = ".qoder-cn"
    workspace_marker = "qoderworkcn-workspace"


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

    Quest tasks carry real titles ("驾驶舱便捷启停说明") that never reach the
    JSONL transcripts; they live in the IDE's global state DB
    (``%APPDATA%/QoderCN/User/globalStorage/state.vscdb``, key
    ``aicoding.questTaskListSnapshot``).  When that snapshot is readable the
    task title wins over the first-user-message heuristic.
    """

    cli = "qodercn-ide"
    projects_dirname = ".qoder-cn"
    # Variant-specific locations: the IDE's global state DB (quest titles) and
    # the matching qoderwake store (board titles for qs_* sessions).
    appdata_product = "QoderCN"
    wake_store = ".qoderwake-cn"

    # Interactive chat writes one `add_user_message` fragment file per user turn.
    # Consecutive fragments in one cwd are one conversation; listing each as a
    # separate session fragments the chat (the IDE shows them unified). Merge
    # fragments whose starts are within this window.
    _FRAG_GAP_MINUTES = 60

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root)
        self._quest_titles: dict[str, str] | None = None
        self._quest_active: set[str] = set()
        self._quest_archived: set[str] = set()
        self._quest_db_readable = False
        self._frag_ids: set[str] = set()
        self._frag_groups: dict[str, list[str]] = {}

    def _peek(self, path: Path):
        meta = super()._peek(path)
        if meta is not None:
            # Detect qoder per-turn fragments from the early session_meta row.
            # The parent peek just built this same version key from the walk's
            # directory entry; asking the OS again here was 2,434 stats a rebuild.
            ver = self._version(path)
            fkey = (str(path), ver[0], ver[1]) if ver else None
            if fkey is not None:
                known = _FRAG_HEAD_CACHE.get(fkey)
                if known is not None:
                    if known:
                        self._frag_ids.add(meta.session_id)
                    return meta
            frag = False
            for r in read_jsonl(path, limit=6):
                if r.get("type") == "session_meta":
                    st2 = (r.get("data") or {}).get("content", {}).get("session_type")
                    frag = st2 == "add_user_message"
                    break
            if fkey is not None:
                if len(_FRAG_HEAD_CACHE) > 8192:
                    _FRAG_HEAD_CACHE.clear()
                _FRAG_HEAD_CACHE[fkey] = frag
            if frag:
                self._frag_ids.add(meta.session_id)
        return meta

    def _list_all(self) -> list[SessionMeta]:
        """Every session in the shared store, before family filtering.

        The wake/work families live in the same store, so their parsers reuse
        this pipeline (fragment merge/absorb, official titles) and filter the
        other direction.
        """
        self._frag_ids = set()
        self._frag_groups = {}
        metas = super().list_sessions()
        titles = self._load_quest_titles()
        wake = self._wake_titles()
        for m in metas:
            t = titles.get(m.session_id) or wake.get(m.session_id)
            if t:
                m.title = t

        # Absorb fragments whose single user message already lives inside a real
        # (task/uuid) session — those are redundant turn-echoes of a conversation
        # that is listed in its own right. Then merge whatever fragments remain.
        absorbed = self._absorbed_fragment_ids(metas)

        # Merge consecutive add_user_message fragments into one conversation so
        # a chat with N turns is one entry, not N.
        frags = sorted(
            (m for m in metas if m.session_id in self._frag_ids and m.session_id not in absorbed),
            key=lambda m: m.started_at or m.updated_at or "",
        )
        reals = [m for m in metas if m.session_id not in self._frag_ids]
        merged: list[SessionMeta] = []
        group: list[SessionMeta] = []

        def flush() -> None:
            if not group:
                return
            if len(group) >= 2:
                rep = group[0]
                self._frag_groups[rep.session_id] = [g.session_id for g in group]
                rep.updated_at = max((g.updated_at or "" for g in group), default=rep.updated_at)
                rep.title = f"{rep.title}（{len(group)} 轮对话）"
                merged.append(rep)
            else:
                merged.append(group[0])

        for m in frags:
            if group and (m.cwd or "") == (group[-1].cwd or "") and self._within_gap(group[-1], m):
                group.append(m)
            else:
                flush()
                group = [m]
        flush()

        out = reals + merged
        # Tool loops are *not* filtered out here: this pipeline serves the whole
        # shared store, and four entries read two stores. Each family's
        # `list_sessions` splits them after its own family filter, so a row is
        # reported hidden by exactly one entry (see `_split_toolloops`).
        # Quest-task transcripts live under <project>/transcript/ and surface
        # in the product's task panel, not its chat list. Tag them so the
        # cockpit can group/filter like the product does.
        for m in out:
            try:
                is_transcript = Path(m.source_path).parent.name == "transcript"
            except (ValueError, OSError):
                continue
            if is_transcript:
                m.task_type = "quest-task"
        # The product tags a task-panel entry whose session is gone as
        # archived-or-deleted. Mirror it: a task-execution transcript whose id
        # the (readable) snapshot knows in neither list gets the badge. An
        # unreadable snapshot means unknown — never a badge.
        if self._quest_db_readable:
            known = self._quest_active | self._quest_archived
            for m in out:
                if ".session.execution" in m.session_id:
                    task_id = m.session_id.split(".session.execution")[0]
                    if task_id and task_id not in known:
                        m.notes = [*m.notes, "snapshot_archived"]
        out.sort(key=lambda m: m.updated_at or "", reverse=True)
        return out

    def list_sessions(self) -> list[SessionMeta]:
        """The IDE's own chats only: wake/work families leave the shared store
        for their own CLI entries (still deep-linkable by id via load())."""
        out = [m for m in self._list_all() if _family_of_path(self.root, m.source_path) is None]
        metas = self._split_toolloops(out)
        for m in metas:
            self._listing_stamp[m.session_id] = m.updated_at
        return metas

    def _within_gap(self, a: SessionMeta, b: SessionMeta) -> bool:
        ta = _parse_iso_local(a.started_at or a.updated_at)
        tb = _parse_iso_local(b.started_at or b.updated_at)
        if ta is None or tb is None:
            return False
        return abs((tb - ta).total_seconds()) <= self._FRAG_GAP_MINUTES * 60

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """Verbatim files of the WHOLE conversation: when a chat was merged
        from per-turn fragments, every fragment file is carried too."""
        group = self._frag_groups.get(session_id)
        if group and len(group) > 1:
            paths: list[Path] = []
            for fid in group:
                paths.extend(self._resolve_group(fid))
            return self._raw_entries(paths)
        return super().raw_archive(session_id)

    def _fragment_user_text(self, session_id: str) -> str:
        """The single user message of an add_user_message fragment file."""
        for path in self._resolve_group(session_id):
            for r in read_jsonl(path, limit=8):
                role, text, _raw, _tools = self._row_content(r)
                if role == "user" and text:
                    return text.strip()
        return ""

    def _absorbed_fragment_ids(self, metas: list[SessionMeta]) -> set:
        """Fragment session ids whose user text already exists in a real session.

        qoder writes every user turn as an ``add_user_message`` fragment AND keeps
        the same message inside the task/uuid conversation. Listing both shows one
        conversation twice; the fragment is the redundant copy, so it is absorbed.
        Result is cached per store (invalidated by newest file mtime) and the scan
        is byte-capped so a large store cannot stall a dashboard load. Each text
        the scan proves is remembered together with the version of the file that
        proved it, so the next scan only answers for fragments whose proof is
        missing: a proof that lapsed - the session that carried it was rewritten
        or deleted - is re-derived rather than trusted. What the scan also
        remembers, per file version, is the list of texts it did *not* find, so a
        store that is being appended to does not re-read the files whose answer
        cannot have changed; the byte budget is still spent on them, which keeps
        the set of files a scan consults - and so what it can absorb - exactly
        what it was before.
        """
        frag_metas = [m for m in metas if m.session_id in self._frag_ids]
        if not frag_metas:
            return set()
        files: list[Path] = []
        try:
            # The caller listed this store moments ago; re-globbing it here to
            # ask "what is the newest file" cost a second full walk per store per
            # poll for a number the listing already held.
            files = sorted({p for group in self._index.values() for p in group})
            if not files:
                files = self._iter_jsonl()
        except (OSError, ValueError):
            files = []
        versions = {}
        for p in files:
            ver = self._version(p)
            if ver is not None:
                versions[p] = ver
        # None when the store said nothing: an empty store, or one whose files
        # all vanished mid-walk. Same as the old `max()` raising ValueError.
        sig = max((v[0] for v in versions.values()), default=None)
        cache_key = str(self.root)
        cached = _QODER_ABSORB_CACHE.get(cache_key)
        if cached is not None and cached[0] == sig:
            return cached[1]

        frag_texts: dict[str, str] = {}
        for m in frag_metas:
            txt = self._fragment_user_text(m.session_id)
            if txt:
                frag_texts[m.session_id] = txt
        proven = _PROVEN_ABSORBED_TEXTS.setdefault(cache_key, {})
        absent = _ABSORB_ABSENT_TEXTS.setdefault(cache_key, {})
        live: dict[str, tuple] = {}
        for txt, proof in proven.items():
            try:
                stp = Path(proof[0]).stat()
            except OSError:
                continue
            if (stp.st_mtime, stp.st_size) == proof[1:]:
                live[txt] = proof
        wanted = {t for t in frag_texts.values() if t not in live}
        if wanted:
            real_paths = sorted(
                (p for p in files if p.stem not in self._frag_ids),
                key=lambda p: versions.get(p, (-1.0, 0))[0],
                reverse=True,
            )
            scanned = 0
            for path in real_paths:
                if not wanted or scanned > _ABSORB_SCAN_CAP_BYTES:
                    break
                version = versions.get(path)
                if version is None:  # unreadable now: it cannot prove anything
                    continue
                scanned += version[1]
                seen = absent.get(str(path))
                if seen is not None and seen[0] == version:
                    # Read once, answered forever (until this file's version
                    # moves): these texts are not in it. Skipping the re-read is
                    # the whole point of the record - the byte budget above is
                    # still spent, so the set of files this scan consults - and
                    # therefore what it can prove - is the same as when every
                    # file was read every time.
                    wanted.difference_update(seen[1])
                    continue
                for row in read_jsonl(path):
                    if row.get("type") != "user":
                        continue
                    role, text, _raw, _tools = self._row_content(row)
                    if role == "user" and text and text.strip() in wanted:
                        wanted.discard(text.strip())
                        proven[text.strip()] = (str(path), *version)
                        # The proof is this file's version, which the scan just
                        # read off `versions`: it counts for this answer, not only
                        # for the next poll.
                        live[text.strip()] = proven[text.strip()]
                        if not wanted:
                            break
                if wanted:
                    # Every text still standing was looked for in this file and
                    # not found: it is absent from *this version* of it. A scan
                    # that proved its last text mid-file records nothing, since
                    # it only read a prefix.
                    absent[str(path)] = (version, frozenset(wanted))
                if len(absent) > 4096:  # a long-lived process, a growing store
                    absent.clear()
            if len(proven) > 4096:  # a long-lived process, a growing store
                proven.clear()
        absorbed = {sid for sid, txt in frag_texts.items() if txt in live}
        if sig is not None:
            _QODER_ABSORB_CACHE[cache_key] = (sig, absorbed)
        return absorbed

    def load(self, session_id: str):
        """Load (+ merge grouped fragments) and re-apply the official title.

        The cockpit detail view rebuilds the bundle from load(), so the meta
        title must carry the same quest/wake overlay the list shows — otherwise
        the two views disagree about a session's name.
        """
        group = self._frag_groups.get(session_id)
        if group and len(group) > 1:
            paths: list[Path] = []
            for fid in group:
                paths.extend(self._resolve_group(fid))
            raw = self._load_paths(paths, session_id) if paths else None
        else:
            raw = super().load(session_id)
        if raw is None:
            return None
        official = self._load_quest_titles().get(session_id) or self._wake_titles().get(session_id)
        if official:
            raw.meta.title = official
        # The CLI's per-file telemetry (.qoder-cli/ai-stats) names the exact
        # files this session's agent touched, keyed by the same session id.
        # File-only supplement like the qodersec anchors — never dialogue.
        # Fixture trees never merge (evidence must measure the transcript).
        try:
            rooted = self.root.resolve().is_relative_to(home().resolve())
        except (OSError, ValueError):
            rooted = False
        if rooted:
            tele = self.telemetry_anchors(session_id)
            if tele:
                for pth, n in tele.items():
                    raw.files_touched[pth] = raw.files_touched.get(pth, 0) + n
                raw.meta.notes = [*raw.meta.notes, f"aistats_files:{len(tele)}"]
            selector = self._model_selector(session_id)
            if selector:
                raw.meta.notes = [*raw.meta.notes, f"model_selector:{selector}"]
                # The IDE's own per-session routing record (e.g. auto):
                # backfill turns that carry no model so every message shows
                # the serving routing. Tokens stay absent (honest).
                for m in raw.messages:
                    if m.role == "assistant" and not m.model:
                        m.model = selector
            if not raw.meta.model:
                anchor = self._workspace_model_anchor(session_id, raw.meta.cwd)
                if anchor:
                    raw.meta.notes = [*raw.meta.notes, f"workspace_model:{anchor}"]
            n_log = self._apply_log_models(raw)
            if n_log:
                raw.meta.notes = [*raw.meta.notes, f"log_models:{n_log}"]
            task_files = self._task_execution_files(session_id)
            if task_files:
                for pth in task_files:
                    raw.files_touched[pth] += 1
                raw.meta.notes = [*raw.meta.notes, f"task_files:{len(task_files)}"]
        return raw

    def _task_execution_files(self, session_id: str) -> list[str]:
        """Exact-match file supplement for quest-task sessions.

        ``~/.qodersec/state/*/<task-id>.session.execution.json`` shares the
        task id with the transcript filename, so unlike the global
        execution_anchors merge this attributes touched paths to the exact
        session. Dialogue untouched; file anchors only.
        """
        from agent_handoff.locations import home

        if ".session.execution" not in session_id:
            return []
        task_id = session_id.split(".session.execution")[0]
        state = home() / ".qodersec" / "state"
        if not state.is_dir():
            return []
        out: list[str] = []
        for path in state.rglob(f"{task_id}.session.execution.json"):
            if path.name.endswith(".lock"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            touched = data.get("touched_paths") or []
            if isinstance(touched, list):
                out.extend(p for p in touched if isinstance(p, str) and p.strip())
        return out

    def _anchor_facts(self, paths, *, cap: bool):
        """(model, casefolded cwds, earliest ts, latest ts, ts count) for one group.

        This IS the anchor's inner loop, so a cached entry and a freshly computed
        one cannot diverge -- the cache stores what the scan would have seen, not a
        re-derivation of it. Only the extremes and a count are kept (that is all the
        anchor asks), because holding 4,000 timestamp strings per session would make
        the cache cost more than the scan it saves.

        `cap` is part of the key: the sibling walk stops at the first 4,000
        timestamps once it has a model, while the session asking the question is
        read in full. Those are different scans and must not share an entry.
        """
        key = (tuple(sorted(str(p) for p in paths)), cap)
        stamp = _newest_mtime([paths])
        hit = _ANCHOR_FACTS.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        model: str | None = None
        cwds: set[str] = set()
        first = last = ""
        count = 0
        for path in paths:
            for row in read_jsonl(path):
                if row.get("type") == "runtime-config" and isinstance(row.get("model"), str):
                    model = row["model"]
                ts = _iso(row.get("timestamp"))
                if ts:
                    count += 1
                    if not first or ts < first:
                        first = ts
                    if not last or ts > last:
                        last = ts
                c = row.get("cwd")
                if isinstance(c, str) and c:
                    cwds.add(c.casefold())
                if cap and model and count > 4000:
                    break
            if cap and model and first:
                break
        facts = (model, cwds, first, last, count)
        _ANCHOR_FACTS[key] = (stamp, facts)
        return facts

    def _workspace_model_anchor(self, session_id: str, cwd: str) -> str | None:
        """Same-workspace, time-overlapping sibling's runtime-config model.

        task-/quest-class sessions carry no model of their own, but a uuid
        sibling in the same cwd whose time range overlaps this session was
        served under its runtime-config model. INFERENCE, not measurement:
        recorded as a note (never Message.model), so the cockpit can show
        it as a hint while the honest-absence rule stays intact.

        The per-group facts come from `_anchor_facts`, which caches them: without
        that, one `load()` re-read every sibling in the store (6,650 files and
        78,781 rows measured on this machine's qoder-ide store, for a session
        whose own file is 0.1 MiB).
        """
        try:
            me_paths = self._resolve_group(session_id)
        except (OSError, ValueError):
            return None
        _m, me_cwds, me_start, me_end, me_n = self._anchor_facts(me_paths, cap=False)
        if not me_n:
            return None
        # Candidates come from the index the store listing already built; asking
        # for a fresh listing here made one session open re-scan the whole store
        # -- 6,501 of the 6,667 `read_jsonl` calls in one measured `load()` came
        # from `list_sessions`, not from anything about that session. Walking the
        # index instead was checked against the listing order on every session in
        # this store that asks the question: **0 of 893 answers differed**
        # (spec Round 49), and the loop below already ignored any id missing
        # from the index, so no candidate is newly in or out of scope.
        index = getattr(self, "_index", None) or {}
        if not index:
            self.list_sessions()
            index = getattr(self, "_index", None) or {}
        # Compare by the cwd recorded INSIDE the rows (project dir names
        # differ in case/separators across the family's layouts); the meta
        # cwd may be a project dir instead of the workdir.
        for sid in index:
            if sid == session_id:
                continue
            try:
                sib_paths = self._resolve_group(sid)
            except (OSError, ValueError):
                continue
            sib_model, sib_cwds, sib_first, sib_last, _c = self._anchor_facts(
                sib_paths, cap=True
            )
            if not sib_model or not sib_first:
                continue
            if not (me_cwds & sib_cwds):
                continue
            if max(sib_first, me_start) <= min(sib_last, me_end):
                return f"{sib_model}（同工作区同时段会话 {sid[:8]}…，推断仅供参考）"
        return None

    def _model_selector(self, session_id: str) -> str | None:
        """The IDE's per-session model routing record.

        Each workspace's ``state.vscdb`` keeps
        ``chat.modelMapSession.<sessionId>`` (e.g. ``auto`` = IDE-routed).
        It names the routing, not the serving model — recorded as a note,
        never as Message.model.
        """
        import os
        import sqlite3

        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        base = Path(appdata) / self.appdata_product / "User" / "workspaceStorage"
        if not base.is_dir():
            return None
        for db in sorted(base.rglob("state.vscdb")):
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
                try:
                    row = con.execute(
                        "SELECT value FROM ItemTable WHERE key=?",
                        (f"chat.modelMapSession.{session_id}",),
                    ).fetchone()
                finally:
                    con.close()
            except (sqlite3.Error, OSError):
                continue
            if row and row[0]:
                return str(row[0])[:60]
        return None

    def telemetry_anchors(
        self, session_id: str, stats_dir: Path | None = None
    ) -> Counter[str]:
        """Per-session file telemetry from the CLI's own ai-stats store.

        ``~/.qoder-cli/ai-stats/projects/*/*.jsonl`` rows carry ``filePath``
        plus ``lineDetails[].sessionId`` — the same id space as this parser's
        sessions. Only the international ``qoder-ide`` variant keeps this store;
        the CN twin has none (returns empty there).

        The whole tree is indexed once and the session looked up in it. Asking
        per session used to re-read everything: measured on this machine, **3,332
        files and 73.9 MB for one detail page** — 53% of that page's wall time and
        99.7% of its reads — and 171 GB for a pass over all 2,305 sessions the
        store lists. The index is keyed on a stat-only signature of the tree, so a
        write to the stats store re-reads and an unchanged one reads nothing, and
        files are streamed line by line: a ``read_text`` of an unbounded file is
        what reached ``MemoryError`` here once (2026-09-22, on a 全量 probe audit).
        """
        return Counter(self._telemetry_index(stats_dir).get(session_id) or {})

    def _telemetry_index(self, stats_dir: Path | None) -> dict[str, Counter[str]]:
        """``sessionId -> filePath counts`` for every row the stats tree holds."""
        from agent_handoff.locations import home

        base = stats_dir or home() / ".qoder-cli" / "ai-stats" / "projects"
        if not base.is_dir():
            return {}
        key = str(base)
        stamp: list[tuple[str, int, int]] = []
        try:
            for p in sorted(base.rglob("*.jsonl")):
                try:
                    st = p.stat()
                except OSError:
                    continue
                stamp.append((str(p), st.st_size, st.st_mtime_ns))
        except OSError:
            return {}
        signature = tuple(stamp)
        hit = _TELE_INDEX.get(key)
        if hit is not None and hit[0] == signature:
            return hit[1]
        index: dict[str, Counter[str]] = {}
        for path, _size, _mtime in stamp:
            try:
                with Path(path).open(encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        _tele_line(line, index)
            except OSError:
                continue
        if len(_TELE_INDEX) > 8:
            _TELE_INDEX.clear()
        _TELE_INDEX[key] = (signature, index)
        return index

    def _wake_titles(self) -> dict[str, str]:
        """qs_* session titles from the QoderWake board projection (read-only)."""
        try:
            import sqlite3

            db = home() / self.wake_store / "data" / "store" / "qoderwake.sqlite"
            if not db.is_file():
                return {}
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT source_task_id, title FROM board_task_projection "
                    "WHERE title IS NOT NULL AND title != ''"
                ).fetchall()
            finally:
                conn.close()
            return {str(s): str(t) for s, t in rows if s and t}
        except Exception:
            return {}

    def _load_quest_titles(self) -> dict[str, str]:
        """Map executionSessionId -> title from the IDE global state DB.

        Also records which task ids the snapshot knows (active vs archived
        list) and whether the DB was readable at all: a task transcript with
        no snapshot entry is only "archived or deleted" when the snapshot
        itself could be read — absence of the DB means unknown, never a badge.
        """
        if self._quest_titles is not None:
            return self._quest_titles
        titles: dict[str, str] = {}
        try:
            import sqlite3

            appdata = os.environ.get("APPDATA")
            if not appdata:
                self._quest_titles = titles
                return titles
            db = Path(appdata) / self.appdata_product / "User" / "globalStorage" / "state.vscdb"
            if not db.is_file():
                self._quest_titles = titles
                return titles
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT key, value FROM ItemTable WHERE key IN "
                    "('aicoding.questTaskListSnapshot', 'aicoding.questArchivedTaskList')"
                ).fetchall()
            finally:
                conn.close()
            self._quest_db_readable = True
            for key, blob in rows:
                if not blob:
                    continue
                try:
                    snap = json.loads(blob)
                except ValueError:
                    continue
                # snapshot: {folders:{path:{tasks:[...]}}}; archived list may be
                # {folders:...} too or a bare list of tasks.
                task_lists: list[list] = []
                if isinstance(snap, dict) and isinstance(snap.get("folders"), dict):
                    for fdata in snap["folders"].values():
                        if isinstance(fdata, dict) and isinstance(fdata.get("tasks"), list):
                            task_lists.append(fdata["tasks"])
                elif isinstance(snap, list):
                    task_lists.append(snap)
                if key == "aicoding.questTaskListSnapshot":
                    known = self._quest_active
                else:
                    known = self._quest_archived
                for tasks in task_lists:
                    for task in tasks:
                        if not isinstance(task, dict):
                            continue
                        sid = task.get("executionSessionId") or task.get("designSessionId")
                        if sid:
                            known.add(str(sid))
                        title = task.get("title") or task.get("name") or task.get("query")
                        # "Untitled" is the IDE's empty placeholder; it is worse
                        # than the transcript-derived title it would displace.
                        if str(title).strip().lower() in ("untitled", "无标题", ""):
                            continue
                        if sid and title:
                            titles[str(sid)] = str(title)
        except Exception:  # DB locked, schema drift, no sqlite — titles stay heuristic
            pass
        self._quest_titles = titles
        return titles


class QoderIdeParser(QodercnIdeParser):
    """Qoder IDE (international edition) — same layout under ~/.qoder.

    The international and CN builds are separate installs with separate stores
    (``.qoder`` vs ``.qoder-cn``) and separate state DBs (``%APPDATA%/Qoder``
    vs ``%APPDATA%/QoderCN``); everything else — dialect, quest titles, the
    qoderwake board overlay — behaves identically.
    """

    cli = "qoder-ide"
    projects_dirname = ".qoder"
    appdata_product = "Qoder"
    wake_store = ".qoderwake"

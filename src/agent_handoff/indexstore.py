"""Persistent layer for the search index: one SQLite file under ~/.agenthandoff.

Why persist: the in-memory haystack cache is useless across processes, so
``handoff search --body`` re-parsed all ~450 sessions (15 s) on *every* run and
a restarted cockpit started cold. The stores themselves are ~400 MB of JSONL
and zstd rolls; the extracted dialogue, zlib-compressed, is a few dozen MB.

Constitution check — this repo promises "read-only: never write beside a CLI's
session store". That promise holds: the only path this module can touch is
``~/.agenthandoff/``, which is already this tool's own state directory
(exchange bundles, backups, domains.toml). ``tests/test_search.py`` asserts no
parser store is ever opened for writing.

Durability is deliberately *optional*: every failure here (locked db, missing
directory, unreadable home) degrades to memory-only search and is reported in
``index_status()["persisted"]`` — a search tool must still work.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path

SCHEMA_VERSION = 2
_DB_NAME = "search-index.sqlite3"
_LOCK = threading.RLock()


def index_path() -> Path:
    """Where the index lives. Our own state dir, never a CLI store."""
    return Path.home() / ".agenthandoff" / _DB_NAME


_ENTRIES_COLUMNS = ("cli", "sid", "src", "fp", "hay", "files")
_ENTRIES_DDL = (
    "CREATE TABLE IF NOT EXISTS entries ("
    " cli TEXT NOT NULL, sid TEXT NOT NULL, src TEXT NOT NULL,"
    " fp TEXT NOT NULL, hay BLOB NOT NULL, files BLOB NOT NULL,"
    " PRIMARY KEY (cli, sid, src))"
)


class IndexStore:
    """Rows of (cli, sid, src) -> (fingerprint, dialogue text, file anchors).

    Text is stored zlib-compressed as a BLOB; a corrupt row is treated as a
    miss (self-healing on the next rebuild) instead of raising.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        # A str is a normal thing to hand a path-based constructor (CLI args,
        # JSON, subprocess argv). Storing it verbatim made `_connect()` call
        # `.parent` on a string - an AttributeError, not a handled failure.
        self.path = Path(path) if path else index_path()
        self._conn: sqlite3.Connection | None = None
        self._ok = False
        self._last_error = ""
        # Rows we wanted to persist but could not. Surfaced in stats() so a
        # cache that drops writes cannot pretend it kept them.
        self._write_failures = 0

    # -- lifecycle -----------------------------------------------------------
    def _connect(self) -> sqlite3.Connection | None:
        if self._conn is not None:
            return self._conn
        attempts = 6
        for attempt in range(attempts):
            conn = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
                )
                # Migrate by dropping — but decide from the *actual columns*, not
                # from the recorded version: a version marker can lie (an earlier
                # build of this file stamped schema_version=2 onto a v1-shaped
                # table, and every write then failed forever). The index is a
                # cache, so rebuilding is always the correct repair.
                #
                # Two processes opening a cold file at once both saw "not current",
                # both dropped the table, and the second DROP wiped the first one's
                # rows. BEGIN IMMEDIATE serializes the check-and-migrate so exactly
                # one process migrates.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    if not self._schema_current(conn):
                        conn.execute("DROP TABLE IF EXISTS entries")
                        conn.execute(_ENTRIES_DDL)
                        self._write_meta(conn, "schema_version", str(SCHEMA_VERSION))
                    conn.commit()
                except sqlite3.Error:
                    conn.rollback()
                    raise
                self._conn = conn
                self._ok = True
                return self._conn
            except (OSError, sqlite3.Error, ValueError) as exc:
                self._last_error = str(exc)
                locked = isinstance(exc, sqlite3.OperationalError) and (
                    "locked" in str(exc).lower() or "busy" in str(exc).lower()
                )
                with contextlib.suppress(sqlite3.Error, OSError):
                    if conn is not None:
                        conn.close()
                if locked and attempt < attempts - 1:
                    # Another process holds the file right now. That is ordinary
                    # for two cockpits on one index; wait it out instead of
                    # demoting this store to memory-only on a single collision.
                    time.sleep(0.05 * (attempt + 1))
                    continue
                self._ok = False
                self._conn = None
                return None
        self._ok = False
        self._conn = None
        return None

    @staticmethod
    def _schema_current(conn: sqlite3.Connection) -> bool:
        """True only when the table exists with exactly the expected columns."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)")}
        if cols != set(_ENTRIES_COLUMNS):
            return False
        return IndexStore._read_meta(conn, "schema_version") == str(SCHEMA_VERSION)

    @staticmethod
    def _read_meta(conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (key, value))

    @property
    def available(self) -> bool:
        with _LOCK:
            self._connect()
            return self._ok

    # -- crud ----------------------------------------------------------------
    def get(self, cli: str, sid: str, src: str, fingerprint: str) -> tuple[str, str] | None:
        """Return (hay, files) when the stored row still matches ``fingerprint``."""
        conn = self._guarded_connect()
        if conn is None:
            return None
        try:
            with _LOCK:
                row = conn.execute(
                    "SELECT fp, hay, files FROM entries WHERE cli = ? AND sid = ? AND src = ?",
                    (cli, sid, src),
                ).fetchone()
        except sqlite3.Error:
            self._ok = False
            return None
        if not row or row[0] != fingerprint:
            return None
        try:
            return (_decode(row[1]), _decode(row[2]))
        except zlib.error:  # pragma: no cover - corrupt blob: treat as a miss
            return None

    def put(self, cli: str, sid: str, src: str, fingerprint: str, hay: str, files: str) -> bool:
        """Persist one row. Returns False (and counts it) when it could not.

        Two processes can contend on the WAL; a `database is locked` after the
        busy timeout used to be swallowed and the row silently dropped. Retrying
        with backoff resolves ordinary contention, and whatever still fails is
        counted and reported rather than pretended away.
        """
        conn = self._guarded_connect()
        if conn is None:
            return False
        payload = (
            cli,
            sid,
            src,
            fingerprint,
            zlib.compress(hay.encode("utf-8"), 6),
            zlib.compress(files.encode("utf-8"), 6),
        )
        attempts = 5
        for attempt in range(attempts):
            try:
                with _LOCK:
                    conn.execute(
                        "INSERT OR REPLACE INTO entries (cli, sid, src, fp, hay, files)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        payload,
                    )
                    conn.commit()
                return True
            except sqlite3.OperationalError as exc:
                locked = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if locked and attempt < attempts - 1:
                    with contextlib.suppress(sqlite3.Error):
                        conn.rollback()
                    time.sleep(0.05 * (attempt + 1))
                    continue
                self._ok = False
                self._last_error = str(exc)
                self._write_failures += 1
                return False
            except sqlite3.Error as exc:  # corrupt db, disk full, ...
                self._ok = False
                self._last_error = str(exc)
                self._write_failures += 1
                return False
        return False

    def keys(self) -> list[tuple[str, str, str]]:
        conn = self._guarded_connect()
        if conn is None:
            return []
        try:
            with _LOCK:
                rows = conn.execute("SELECT cli, sid, src FROM entries").fetchall()
        except sqlite3.Error:
            self._ok = False
            return []
        return [(r[0], r[1], r[2]) for r in rows]

    def clear(self) -> None:
        conn = self._guarded_connect()
        if conn is None:
            return
        try:
            with _LOCK:
                conn.execute("DELETE FROM entries")
                conn.commit()
        except sqlite3.Error:  # pragma: no cover
            self._ok = False

    def stats(self) -> dict:
        conn = self._guarded_connect()
        out = {
            "persisted": self._ok,
            "path": str(self.path),
            "rows": 0,
            "bytes": 0,
            "write_failures": self._write_failures,
        }
        if conn is None:
            out["persisted"] = False
            if self._last_error:
                out["persist_error"] = self._last_error
            return out
        try:
            with _LOCK:
                out["rows"] = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        except sqlite3.Error:  # pragma: no cover
            self._ok = False
        with contextlib.suppress(OSError):  # a size read is diagnostics, not correctness
            out["bytes"] = self.path.stat().st_size if self.path.exists() else 0
        return out

    def note(self, payload: dict) -> None:
        """Record a build summary (sessions, duration) for diagnostics."""
        conn = self._guarded_connect()
        if conn is None:
            return
        try:
            with _LOCK:
                self._write_meta(conn, "last_build", json.dumps(payload, sort_keys=True))
                conn.commit()
        except sqlite3.Error:  # pragma: no cover
            self._ok = False

    def last_build(self) -> dict | None:
        conn = self._guarded_connect()
        if conn is None:
            return None
        try:
            with _LOCK:
                raw = self._read_meta(conn, "last_build")
        except sqlite3.Error:  # pragma: no cover
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:  # pragma: no cover
            return None

    def _guarded_connect(self) -> sqlite3.Connection | None:
        with _LOCK:
            if not self._ok and self._conn is not None:
                return None  # already demoted this process to memory-only
            return self._connect()


def _decode(blob: bytes | str) -> str:
    if isinstance(blob, str):  # a row written by an older schema
        return blob
    return zlib.decompress(blob).decode("utf-8", "replace")

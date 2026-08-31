r"""Publishable-data invariants, shared by the generator and the test suite.

Why this lives in the library: the checks that a fixture is safe to commit have to
run in two places - when the maintainer builds it, and in CI on a machine where
the username is a different string entirely. Anything keyed to the current
account (a home path, a project directory name) can only be audited at build
time; what CAN travel is the structural set below, and it is precise enough to
catch the leaks that were actually found here: vendor-munged paths
(`C--Users-c-zh-...`), profile segments (`\Documents\`, `\AppData\`), and secrets.

The scan walks SQLite cells and inflates zlib streams, because a compressed BLOB
hides from a byte scan - which is a leak the reviewer never sees and the user
eventually does.
"""

from __future__ import annotations

import re
import sqlite3
import zlib
from pathlib import Path

# A path segment that only exists on a real person's machine. Delimiters are
# required on both sides so ordinary words ("user", "home screen") survive.
PERSONAL_SEGMENT_RE = re.compile(
    r"[\\/\-](?:users?|home|var|mnt|volumes|documents?|desktop|downloads|appdata|roaming)"
    r"[\\/\-]",
    re.I,
)
# Absolute paths we generate hang off one synthetic root; anything else is
# somebody's disk. Two details learned the hard way: the drive letter must not be
# preceded by a word character (`code:\n128` in grep output is not a path), and
# the path must continue past the first segment, because in JSON `e:\n` is an
# escaped newline that any colon-based regex reads as `e:\...`.
DRIVE_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]{1,2}([A-Za-z0-9_.\-\u4e00-\u9fff]{2,40})[\\/]{1,2}"
)
SYNTH_ROOTS = {"work"}
POSIX_REAL_ROOT_RE = re.compile(
    r"(?<![\w.])/(?:home|Users|mnt|Volumes|root|private)(?:[\\/]|$)"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
ALLOWED_EMAIL_HOSTS = ("example.test", "example.com", "localhost")
SECRET_RE = re.compile(r"\b(?:sk|ghp|gho|xox[baprs]|ya29)[_-][0-9A-Za-z]{16,}")
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{12,}\.[A-Za-z0-9_\-]{8,}")
ZLIB_MAGIC = (b"\x78\x9c", b"\x78\x01", b"\x78\xda", b"\x1f\x8b")
SCAN_SUFFIXES = {".sqlite", ".db"}


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', "") + '"'


def try_inflate(raw: bytes) -> bytes | None:
    """Decompress a cell if the magic bytes say it is compressed."""
    if raw[:2] not in ZLIB_MAGIC:
        return None
    try:
        return zlib.decompress(raw)
    except Exception:  # a look-alike prefix, not a zlib stream
        return None


def sqlite_cell_blobs(path: Path, limit: int = 4000) -> list[tuple[str, bytes]]:
    """Every text cell and BLOB in a SQLite store, labelled by column."""
    out: list[tuple[str, bytes]] = []
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        ]
        for name in tables:
            columns = [r[1] for r in con.execute(f'PRAGMA table_info({_quote(name)})')]
            if not columns:
                continue
            cols = ",".join(_quote(c) for c in columns)
            for row in con.execute(f"SELECT {cols} FROM {_quote(name)} LIMIT {limit}"):
                for col, cell in zip(columns, row, strict=False):
                    if isinstance(cell, str):
                        out.append((f"{name}.{col}: ", cell.encode()))
                    elif isinstance(cell, (bytes, bytearray)):
                        raw = bytes(cell)
                        out.append((f"{name}.{col}(blob): ", raw))
                        inflated = try_inflate(raw)
                        if inflated:
                            out.append((f"{name}.{col}(inflated): ", inflated))
                    if len(out) >= limit:
                        return out
    finally:
        con.close()
    return out


def scan_text(text: str, where: str = "") -> list[str]:
    """Reasons this text must not be published."""
    hits: list[str] = []
    match = PERSONAL_SEGMENT_RE.search(text)
    if match:
        hits.append(f"{where}profile path segment {match.group(0)!r}")
    for found in DRIVE_RE.finditer(text):
        if found.group(1) not in SYNTH_ROOTS:
            hits.append(f"{where}absolute path off a real root {found.group(0)[:40]!r}")
    for found in POSIX_REAL_ROOT_RE.finditer(text):
        hits.append(f"{where}absolute path off a real root {found.group(0)[:40]!r}")
    for found in EMAIL_RE.finditer(text):
        if not any(found.group(0).endswith(host) for host in ALLOWED_EMAIL_HOSTS):
            hits.append(f"{where}email {found.group(0)[:48]!r}")
    for pattern, label in (
        (SECRET_RE, "api key"),
        (AWS_KEY_RE, "aws key"),
        (PRIVATE_KEY_RE, "private key"),
        (JWT_RE, "jwt"),
    ):
        found = pattern.search(text)
        if found:
            hits.append(f"{where}{label} {found.group(0)[:24]!r}")
    return hits


def scan_bytes(blob: bytes, where: str = "") -> list[str]:
    return scan_text(blob.decode("utf-8", "replace"), where=where)


def scan_file(path: Path) -> list[str]:
    hits = scan_bytes(path.read_bytes(), where=f"{path.name}: ")
    if path.suffix.lower() in SCAN_SUFFIXES:
        try:
            cells = sqlite_cell_blobs(path)
        except sqlite3.Error:
            return [f"{path.name}: unreadable sqlite fixture"]
        for where, payload in cells:
            hits.extend(scan_bytes(payload, where=f"{path.name}:{where}"))
    return sorted(set(hits))


def scan_tree(root: Path) -> list[str]:
    """Every publishability problem in a directory tree."""
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out.extend(scan_file(path))
    return out

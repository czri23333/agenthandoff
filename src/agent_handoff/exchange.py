"""Multi-agent exchange: publish bundles, list the inbox, claim work.

Design philosophy: **files are the API, git is the bus.** A published bundle
is just a markdown file in a conventional directory — nothing to install on
the receiving side, no daemon, no network protocol. Synchronize across
machines/agents by committing the exchange directory to git (or any file
sync); asynchronous collaboration between co-located agents needs nothing
but the filesystem.

Layouts:

* project scope: ``<cwd>/.handoff/``          (commit it, or gitignore it)
* global scope:  ``~/.agenthandoff/``          (cross-project mailbox)

Claiming writes a sidecar ``<bundle>.claimed.json`` so two agents never pick
up the same handoff unknowingly. The claimed marker is data, not a lock.
"""

from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EXCHANGE_DIRNAME = ".handoff"
GLOBAL_DIRNAME = ".agenthandoff"
CLAIM_SUFFIX = ".claimed.json"


@dataclass
class InboxItem:
    path: Path
    title: str
    cli: str
    session_id: str
    published_at: str
    claimed: bool
    claimed_by: str = ""


def global_dir() -> Path:
    return Path.home() / GLOBAL_DIRNAME


def project_dir(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / EXCHANGE_DIRNAME


def _scope_dir(global_scope: bool, cwd: Path | None) -> Path:
    return global_dir() if global_scope else project_dir(cwd)


def _utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_session_slug(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "", session_id)[:12] or "unknown"


def publish(
    bundle_path: Path,
    global_scope: bool = False,
    note: str | None = None,
    cwd: Path | None = None,
) -> Path:
    """Copy a bundle file into the exchange directory; return the new path."""
    src = Path(bundle_path)
    if not src.is_file():
        raise FileNotFoundError(f"bundle not found: {src}")
    dest_dir = _scope_dir(global_scope, cwd)
    dest_dir.mkdir(parents=True, exist_ok=True)

    text = src.read_text(encoding="utf-8", errors="replace")
    if note:
        stamp = (
            f"\n<!-- published {_utc_slug()} by {socket.gethostname()} — "
            f"note: {note} -->\n"
        )
        text = text.rstrip() + stamp

    sess_slug = "session"
    m = re.search(r'^session_id: "(.*?)"', text, re.M)
    if m:
        sess_slug = _safe_session_slug(m.group(1))
    dest = dest_dir / f"handoff-{_utc_slug()}-{sess_slug}{src.suffix or '.md'}"
    dest.write_text(text, encoding="utf-8")
    return dest


def _read_bundle_header(path: Path) -> dict:
    out = {"title": path.stem, "cli": "?", "session_id": "?", "published_at": ""}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    m = re.search(r"^cli:\s*(\S+)", text, re.M)
    if m:
        out["cli"] = m.group(1)
    m = re.search(r'^session_id:\s*"(.*?)"', text, re.M)
    if m:
        out["session_id"] = m.group(1)
    m = re.search(r'^title:\s*"(.*?)"', text, re.M)
    if m:
        out["title"] = m.group(1)
    m = re.search(r"handoff-(\d{8}T\d{6}Z)-", path.name)
    if m:
        out["published_at"] = m.group(1)
    return out


def inbox(global_scope: bool = False, cwd: Path | None = None) -> list[InboxItem]:
    """List published bundles in the exchange directory, newest first."""
    d = _scope_dir(global_scope, cwd)
    if not d.is_dir():
        return []
    items: list[InboxItem] = []
    for f in sorted(d.glob("handoff-*")):
        if f.suffix not in (".md", ".json") or f.name.endswith(CLAIM_SUFFIX):
            continue
        head = _read_bundle_header(f)
        claimed_by = ""
        claim_file = f.with_name(f.name + CLAIM_SUFFIX)
        if claim_file.exists():
            try:
                claimed_by = str(
            json.loads(claim_file.read_text(encoding="utf-8")).get("claimed_by", "")
        )
            except (json.JSONDecodeError, OSError):
                claimed_by = "?"
        items.append(
            InboxItem(
                path=f,
                title=head["title"],
                cli=head["cli"],
                session_id=head["session_id"],
                published_at=head["published_at"],
                claimed=bool(claimed_by),
                claimed_by=claimed_by,
            )
        )
    items.sort(key=lambda i: i.published_at, reverse=True)
    return items


def claim(bundle_path: Path, claimed_by: str | None = None) -> Path:
    """Mark a published bundle as taken; return the sidecar path."""
    src = Path(bundle_path)
    if not src.is_file():
        raise FileNotFoundError(f"bundle not found: {src}")
    marker = {
        "claimed_by": claimed_by or socket.gethostname(),
        "claimed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
    }
    sidecar = src.with_name(src.name + CLAIM_SUFFIX)
    sidecar.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar

"""Multi-agent exchange: publish bundles, list the inbox, claim work, lease it.

Design philosophy: **files are the API, git is the bus.** A published bundle is
just a markdown file in a conventional directory - nothing to install on the
receiving side, no daemon, no network protocol. Synchronize across machines and
agents by committing the exchange directory to git (or any file sync);
asynchronous collaboration between co-located agents needs nothing but the
filesystem.

Layouts:

* project scope: ``<cwd>/.handoff/``          (commit it, or gitignore it)
* global scope:  ``~/.agenthandoff/``          (cross-project mailbox)

Two agents working the same task is the failure this directory has to prevent,
and a marker file is not enough for that, so both are here:

``claim`` writes ``<bundle>.claimed.json`` **exclusively** (``O_EXCL``). Whoever
loses the race gets ``AlreadyClaimed`` instead of both agents starting the same
work and overwriting each other's conclusions.

``lease`` adds the time dimension a claim has not had: publish with
``--lease-minutes 45`` and the handoff is yours for 45 minutes; a second agent
that tries to claim it is refused until the lease expires, so an agent that is
still working cannot be silently interrupted. Leases are wall-clock and advisory
- they coordinate cooperating agents, they do not defend against a hostile one,
and a clock-skewed host can hold a lease too long. Expired leases are treated as
absent, never as held: a dead agent must not block the work forever.
"""

from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXCHANGE_DIRNAME = ".handoff"
GLOBAL_DIRNAME = ".agenthandoff"
CLAIM_SUFFIX = ".claimed.json"
LEASE_SUFFIX = ".lease.json"
DEFAULT_LEASE_MINUTES = 45.0


class AlreadyClaimed(RuntimeError):
    """Another agent holds the claim (or an unexpired lease)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _parse_iso(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _write_exclusive(path: Path, payload: dict) -> None:
    """Create the file or fail; a sidecar written twice is two agents colliding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise AlreadyClaimed(f"{path.name} already exists") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read_sidecar(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class InboxItem:
    path: Path
    title: str
    cli: str
    session_id: str
    published_at: str
    claimed: bool
    claimed_by: str = ""
    lease_by: str = ""
    lease_until: str = ""

    @property
    def leased(self) -> bool:
        """True while an unexpired lease is held."""
        until = _parse_iso(self.lease_until)
        return bool(self.lease_by) and until is not None and until > _now()


def global_dir() -> Path:
    return Path.home() / GLOBAL_DIRNAME


def project_dir(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / EXCHANGE_DIRNAME


def _scope_dir(global_scope: bool, cwd: Path | None) -> Path:
    return global_dir() if global_scope else project_dir(cwd)


def _utc_slug() -> str:
    return _now().strftime("%Y%m%dT%H%M%SZ")


def _safe_session_slug(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "", session_id)[:12] or "unknown"


def publish(
    bundle_path: Path,
    global_scope: bool = False,
    note: str | None = None,
    cwd: Path | None = None,
    lease_minutes: float | None = None,
    owner: str | None = None,
) -> Path:
    """Copy a bundle into the exchange directory, optionally leasing it to the sender."""
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
    match = re.search(r'^session_id: "(.*?)"', text, re.M)
    if match:
        sess_slug = _safe_session_slug(match.group(1))
    dest = dest_dir / f"handoff-{_utc_slug()}-{sess_slug}{src.suffix or '.md'}"
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)  # a reader never sees a half-written bundle
    if lease_minutes is not None:
        lease(dest, minutes=lease_minutes, owner=owner)
    return dest


def lease(
    bundle_path: Path,
    minutes: float = DEFAULT_LEASE_MINUTES,
    owner: str | None = None,
) -> Path:
    """Hold a handoff for `minutes`; return the lease sidecar."""
    src = Path(bundle_path)
    if not src.is_file():
        raise FileNotFoundError(f"bundle not found: {src}")
    if minutes <= 0:
        raise ValueError("lease minutes must be positive")
    holder = owner or socket.gethostname()
    payload = {
        "leased_by": holder,
        "host": socket.gethostname(),
        "leased_at": _iso(_now()),
        "until": _iso(_now() + timedelta(minutes=minutes)),
        "minutes": minutes,
    }
    sidecar = src.with_name(src.name + LEASE_SUFFIX)
    existing = _read_sidecar(sidecar)
    if _lease_is_live(existing) and existing.get("leased_by") != holder:
        raise AlreadyClaimed(f"leased by {existing['leased_by']} until {existing['until']}")
    # Re-issuing one's own lease is the normal case: write it fresh.
    if sidecar.exists():
        sidecar.unlink()
    _write_exclusive(sidecar, payload)
    return sidecar


def _lease_is_live(data: dict) -> bool:
    until = _parse_iso(str(data.get("until") or ""))
    return bool(data.get("leased_by")) and until is not None and until > _now()


def lease_of(bundle_path: Path) -> dict:
    """The live lease on a handoff, or {} when there is none or it expired."""
    data = _read_sidecar(Path(bundle_path).with_name(Path(bundle_path).name + LEASE_SUFFIX))
    return data if _lease_is_live(data) else {}


def release(bundle_path: Path, owner: str | None = None, force: bool = False) -> bool:
    """Drop a lease. Only the holder may, unless `force` says otherwise."""
    sidecar = Path(bundle_path).with_name(Path(bundle_path).name + LEASE_SUFFIX)
    data = _read_sidecar(sidecar)
    if not sidecar.exists():
        return False
    if not force and owner is not None and data.get("leased_by") not in {owner, None, ""}:
        raise AlreadyClaimed(f"lease belongs to {data.get('leased_by')}")
    sidecar.unlink()
    return True


def _read_bundle_header(path: Path) -> dict:
    out = {"title": path.stem, "cli": "?", "session_id": "?", "published_at": ""}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    match = re.search(r"^cli:\s*(\S+)", text, re.M)
    if match:
        out["cli"] = match.group(1)
    match = re.search(r'^session_id:\s*"(.*?)"', text, re.M)
    if match:
        out["session_id"] = match.group(1)
    match = re.search(r'^title:\s*"(.*?)"', text, re.M)
    if match:
        out["title"] = match.group(1)
    match = re.search(r"handoff-(\d{8}T\d{6}Z)-", path.name)
    if match:
        out["published_at"] = match.group(1)
    return out


def inbox(global_scope: bool = False, cwd: Path | None = None) -> list[InboxItem]:
    """List published bundles in the exchange directory, newest first."""
    directory = _scope_dir(global_scope, cwd)
    if not directory.is_dir():
        return []
    items: list[InboxItem] = []
    for path in sorted(directory.glob("handoff-*")):
        if path.suffix not in (".md", ".json") or path.name.endswith((CLAIM_SUFFIX, LEASE_SUFFIX)):
            continue
        head = _read_bundle_header(path)
        claim_data = _read_sidecar(path.with_name(path.name + CLAIM_SUFFIX))
        lease_data = _read_sidecar(path.with_name(path.name + LEASE_SUFFIX))
        items.append(
            InboxItem(
                path=path,
                title=head["title"],
                cli=head["cli"],
                session_id=head["session_id"],
                published_at=head["published_at"],
                claimed=bool(claim_data.get("claimed_by")),
                claimed_by=str(claim_data.get("claimed_by") or ""),
                lease_by=(
                    str(lease_data.get("leased_by") or "") if _lease_is_live(lease_data) else ""
                ),
                lease_until=(
                    str(lease_data.get("until") or "") if _lease_is_live(lease_data) else ""
                ),
            )
        )
    items.sort(key=lambda item: item.published_at, reverse=True)
    return items


def claim(
    bundle_path: Path,
    claimed_by: str | None = None,
    *,
    respect_lease: bool = True,
    force: bool = False,
) -> Path:
    """Take a handoff. The write is exclusive, so only one agent can win."""
    src = Path(bundle_path)
    if not src.is_file():
        raise FileNotFoundError(f"bundle not found: {src}")
    holder = claimed_by or socket.gethostname()
    live = lease_of(src) if respect_lease else {}
    if live and not force and live.get("leased_by") != holder:
        raise AlreadyClaimed(
            f"leased by {live.get('leased_by')} until {live.get('until')}; "
            "pass --force to take it anyway"
        )
    marker = {
        "claimed_by": holder,
        "claimed_at": _iso(_now()),
        "host": socket.gethostname(),
        "overrode_lease": bool(live) and force and live.get("leased_by") != holder,
    }
    sidecar = src.with_name(src.name + CLAIM_SUFFIX)
    existing = _read_sidecar(sidecar)
    if existing.get("claimed_by"):
        if existing.get("claimed_by") == holder:
            return sidecar  # re-claiming one's own work is not a collision
        if not force:
            raise AlreadyClaimed(
                f"already claimed by {existing['claimed_by']} at {existing.get('claimed_at')}"
            )
        sidecar.unlink()
    elif sidecar.exists():
        sidecar.unlink()  # unreadable marker: replace it rather than deadlock
    _write_exclusive(sidecar, marker)
    return sidecar

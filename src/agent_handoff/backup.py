"""Backup of the user's irreplaceable session stores — export + snapshot.

Round 1: `handoff backup` writes a timestamped archive containing
  - a zip of every discovered session store (SQLite files and JSONL dirs),
  - the current handoff exchange dir (if any), and
  - a manifest.json (store list, file counts, time).

Later rounds add scheduled snapshots and restore tooling; the backup itself is
a plain directory on disk the user can commit, copy, or leave where it is.
"""

from __future__ import annotations

import datetime
import json
import shutil
import zipfile
from pathlib import Path

from agent_handoff.exchange import global_dir, project_dir
from agent_handoff.locations import discover


def _manifest(stores: list, dest: Path) -> dict:
    return {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "stores": [
            {
                "cli": s.cli,
                "path": str(s.path),
                "kind": s.kind,
                "via_wsl": s.via_wsl,
                "detail": s.detail,
            }
            for s in stores
        ],
        "exchange_project": str(project_dir()),
        "exchange_global": str(global_dir()),
        "bundle_version": "0.1",
    }


def backup(dest: Path | None = None) -> Path:
    """Create a backup directory and return its path."""
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = dest or (Path.home() / ".agenthandoff" / "backups" / f"backup-{ts}")
    dest.mkdir(parents=True, exist_ok=True)

    stores = discover()
    payload = json.dumps(_manifest(stores, dest), ensure_ascii=False, indent=2)
    (dest / "manifest.json").write_text(payload, encoding="utf-8")

    stores_dir = dest / "stores"
    stores_dir.mkdir(parents=True, exist_ok=True)
    for s in stores:
        if s.via_wsl:
            # WSL UNC paths are best backed up from inside WSL — skip here,
            # but record them in the manifest so restore can warn.
            continue
        p = Path(s.path)
        if p.is_file():
            shutil.copy2(p, stores_dir / f"{s.cli}__{p.name}")
        elif p.is_dir():
            # Zip the project dirs — otherwise a copy explodes into thousands
            # of jsonl files at top level.
            zip_dest = stores_dir / f"{s.cli}.zip"
            with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as z:
                for f in p.rglob("*"):
                    if f.is_file():
                        z.write(f, f.relative_to(p.parent))

    # Exchange dirs (small — copy directly)
    for ex_dir in [project_dir(), global_dir()]:
        if ex_dir.is_dir() and any(ex_dir.iterdir()):
            target = dest / ("exchange_global" if ex_dir == global_dir() else "exchange_project")
            shutil.copytree(ex_dir, target, dirs_exist_ok=True)

    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    manifest["archived_files"] = sum(1 for _ in dest.rglob("*") if _.is_file())
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    (dest / "manifest.json").write_text(payload, encoding="utf-8")
    return dest

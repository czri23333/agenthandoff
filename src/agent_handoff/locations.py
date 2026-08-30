"""Discover where each supported CLI stores its sessions on this machine.

Probing is read-only; agenthandoff never writes into any CLI's store.
On Windows, stores inside WSL distros are discovered through `wsl.exe` and
read via the `\\wsl.localhost` UNC path with the same parsers.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Relative paths, from the CLI user's home, that identify a session store.
_WSL_KNOWN_STORES = {
    "zcode": ".zcode/cli/db/db.sqlite",
    "claude": ".claude/projects",
    "codebuddy": ".codebuddy/projects",
    "qoderwork": ".qoderwork/projects",
    "qwenwork": ".qwenworkcn/projects",
    "dsh": ".dsh/sessions",
    "kimi": ".kimi-code/sessions",
}


@dataclass
class StoreInfo:
    cli: str
    kind: str  # "sqlite" | "jsonl-dir" | "zstd-dir" | "kimi-dir"
    path: Path
    readable: bool
    detail: str = ""
    via_wsl: bool = False
    distro: str = field(default="")


ENV_HOME = "AGENTHANDOFF_HOME"


def home() -> Path:
    """The user home whose toolchain we inspect.

    Override with AGENTHANDOFF_HOME to point the whole tool at another
    profile — a mounted disk image, a colleague's copy handed over for
    debugging, or a fixture tree. Default is the running user's home.
    """
    override = os.environ.get(ENV_HOME, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home()


# -- Windows-native stores ---------------------------------------------------

def zcode_store() -> StoreInfo | None:
    p = home() / ".zcode" / "cli" / "db" / "db.sqlite"
    if not p.exists():
        return None
    return StoreInfo("zcode", "sqlite", p, _can_open_sqlite(p))


def _projects_store(cli: str, dirname: str) -> StoreInfo | None:
    p = home() / dirname / "projects"
    if not p.is_dir():
        return None
    n = sum(1 for _ in p.rglob("*.jsonl"))
    detail = f"{n} session file(s)"
    accounts = _count_account_configs(home() / dirname)
    if accounts is not None:
        detail += f"; {accounts} account config(s)"
    return StoreInfo(cli, "jsonl-dir", p, n > 0, detail)


def _count_account_configs(store_root: Path) -> int | None:
    """Count per-account model-config directories (.models/<uuid>).

    Some harnesses (e.g. Qoderwork) keep one encrypted model catalog per
    logged-in account under ``.models/<uuid>/``. The contents are opaque by
    design — we only report *how many* account configurations exist, as
    evidence of multi-account usage. Session-level attribution stays with
    the user (``capture --note account:...``) because the stores themselves
    do not record which account produced a session.
    """
    models = store_root / ".models"
    if not models.is_dir():
        return None
    uuid_dirs = [d for d in models.iterdir() if _UUID_DIRNAME.match(d.name)]
    return len(uuid_dirs) or None


_UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_UUID_DIRNAME = re.compile(_UUID_RE)


def claude_code_store() -> StoreInfo | None:
    return _projects_store("claude", ".claude")


def codebuddy_store() -> StoreInfo | None:
    return _projects_store("codebuddy", ".codebuddy")


def codebuddy_cn_store() -> StoreInfo | None:
    return _projects_store("codebuddy-cn", ".codebuddycn")


def qoderwork_store() -> StoreInfo | None:
    return _projects_store("qoderwork", ".qoderwork")


def qoderwork_cn_store() -> StoreInfo | None:
    return _projects_store("qoderwork-cn", ".qoderworkcn")


def qodercn_ide_store() -> StoreInfo | None:
    return _projects_store("qodercn-ide", ".qoder-cn")


def qwenwork_store() -> StoreInfo | None:
    return _projects_store("qwenwork", ".qwenworkcn")


def dsh_store() -> StoreInfo | None:
    p = home() / ".dsh" / "sessions"
    if not p.is_dir():
        return None
    n = sum(1 for _ in p.rglob("session.jsonl.zstd"))
    try:
        import zstandard  # noqa: F401

        codec = "zstd codec present"
    except ImportError:
        codec = "zstd codec missing — pip install 'agenthandoff[zstd]'"
    return StoreInfo("dsh", "zstd-dir", p, n > 0, f"{n} roll(s); {codec}")


def kimi_store() -> StoreInfo | None:
    p = home() / ".kimi-code" / "sessions"
    if not p.is_dir():
        return None
    n = sum(1 for _ in p.glob("wd_*/session_*/state.json"))
    return StoreInfo("kimi", "kimi-dir", p, n > 0, f"{n} session(s); experimental")


def codex_store() -> StoreInfo | None:
    """Codex resolves its own root from $CODEX_HOME; so do we.

    Only file presence is reported here. Whether those files can actually be
    parsed is measured by the parser — `handoff doctor` asks it directly instead
    of repeating a hardcoded verdict.
    """
    override = os.environ.get("CODEX_HOME", "").strip()
    base = Path(override).expanduser() if override else home() / ".codex"
    p = base / "sessions"
    if not p.is_dir():
        return None
    n = sum(1 for _ in p.rglob("*.jsonl"))
    archived = base / "archived_sessions"
    extra = sum(1 for _ in archived.rglob("*.jsonl")) if archived.is_dir() else 0
    detail = f"{n} rollout file(s)" + (f"; {extra} archived" if extra else "")
    if override:
        detail += "; $CODEX_HOME"
    return StoreInfo("codex", "jsonl-dir", p, n > 0, detail)


def _can_open_sqlite(p: Path) -> bool:
    import sqlite3

    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=1)
        con.execute("SELECT 1")
        con.close()
        return True
    except sqlite3.Error:
        return False


# -- WSL bridge ---------------------------------------------------------------

_distro_cache: list[str] | None = None


def wsl_distros() -> list[str]:
    """Enumerate WSL distros (Windows only). Result cached per process."""
    global _distro_cache
    if os.name != "nt":
        return []
    if _distro_cache is not None:
        return _distro_cache
    try:
        out = subprocess.run(
            ["wsl.exe", "-l", "-q"], capture_output=True, timeout=10, check=False
        )
        text = out.stdout.decode("utf-16-le", errors="replace").replace("\x00", "")
        _distro_cache = [ln.strip() for ln in text.splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        _distro_cache = []
    return _distro_cache


def _wsl_home_users(distro: str) -> list[str]:
    try:
        out = subprocess.run(
            ["wsl.exe", "-d", distro, "--", "ls", "/home"],
            capture_output=True, timeout=10, check=False,
        )
        text = out.stdout.decode("utf-8", errors="replace").replace("\x00", "")
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def wsl_stores() -> list[StoreInfo]:
    """Probe known CLI stores inside each WSL distro."""
    found: list[StoreInfo] = []
    for distro in wsl_distros():
        for user in _wsl_home_users(distro):
            for cli, rel in _WSL_KNOWN_STORES.items():
                unc = Path(rf"\\wsl.localhost\{distro}\home\{user}\{rel}")
                try:
                    exists = unc.exists()
                except OSError:
                    exists = False
                if not exists:
                    continue
                if rel.endswith(".sqlite"):
                    found.append(
                        StoreInfo(cli, "sqlite", unc, _can_open_sqlite(unc),
                                  f"[wsl:{distro}]", True, distro)
                    )
                else:
                    found.append(
                        StoreInfo(cli, "jsonl-dir", unc, True, f"[wsl:{distro}]", True, distro)
                    )
    return found


# -- aggregate ----------------------------------------------------------------

def discover() -> list[StoreInfo]:
    """Probe every known CLI store, native then WSL, in a stable order."""
    probes = [
        zcode_store,
        claude_code_store,
        codebuddy_store,
        codebuddy_cn_store,
        qoderwork_store,
        qoderwork_cn_store,
        qodercn_ide_store,
        qwenwork_store,
        dsh_store,
        kimi_store,
        codex_store,
    ]
    found: list[StoreInfo] = []
    for probe in probes:
        info = probe()
        if info is not None:
            found.append(info)
    found.extend(wsl_stores())
    return found


def munge_cwd(cwd: str | Path) -> str:
    """Mangle a working directory the way Claude Code / CodeBuddy name project dirs."""
    s = str(cwd)
    s = s.replace("/", "-").replace("\\", "-").replace(":", "-").replace("_", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")

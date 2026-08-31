"""What the shipped fixtures are, and exactly what they prove.

The support matrix, the conformance gate and the test suite all need the same
answer to "aim this parser at the fixture and tell me what comes out". One module
holding that answer is what keeps a check mark in the README and a pytest
assertion saying the same thing - the previous split is how the README managed to
claim Codex was stable while ``doctor`` could not read it.

A fixture is a sanitized sample of a real store (built by
``scripts/sanitize_fixtures.py``): layout, keys, record types, enums and id shapes
preserved, every string replaced. Its manifest (``.fixture.json``) records where a
parser must be aimed, how many records were sampled away, and how much dialogue the
source sessions held - so "the fixture is thin" is a fact in the repo, not a claim
in a terminal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "sanitized"
BASELINE_ROOT = REPO / "conformance"
MANIFEST_NAME = ".fixture.json"


@dataclass
class Evidence:
    """What one CLI's fixture actually yields when a parser reads it."""

    cli: str
    present: bool = False
    files: int = 0
    sessions: int = 0
    messages: int = 0
    nonempty: int = 0
    tools: int = 0
    files_touched: int = 0
    source_messages: int = 0
    sampled: bool = False
    codec_missing: bool = False
    error: str = ""

    @property
    def shape_only(self) -> bool:
        """The store itself had no dialogue: nothing to prove, nothing hidden."""
        return self.present and self.nonempty == 0 and self.source_messages == 0

    @property
    def unusable(self) -> bool:
        """This environment cannot read the store (an optional codec is missing).

        Reporting zero sessions here would be a lie about the format: it is a
        statement about the environment, so the gate must skip it rather than
        compare a number that depends on which extras happen to be installed.
        """
        return self.codec_missing

    @property
    def proven(self) -> bool:
        """At least one session with at least one non-empty message."""
        return self.present and self.sessions > 0 and self.nonempty > 0

    @property
    def lost_content(self) -> bool:
        """The source had dialogue and the fixture produces none: a build bug."""
        return self.present and self.nonempty == 0 and self.source_messages > 0


def cli_dir(cli: str) -> Path:
    return FIXTURE_ROOT / cli


def manifest(cli: str) -> dict:
    path = cli_dir(cli) / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def root_for(cli: str) -> Path | None:
    """The path ``Parser.with_root`` must be aimed at to read this fixture.

    ``with_root`` in the manifest is stored with forward slashes so a fixture
    generated on Windows still resolves on Linux CI.
    """
    directory = cli_dir(cli)
    if not directory.is_dir():
        return None
    wanted = manifest(cli).get("with_root")
    if wanted:
        parts = [p for p in str(wanted).replace("\\", "/").split("/") if p]
        return FIXTURE_ROOT.joinpath(*parts)
    nested = directory / "sessions"
    return nested if nested.is_dir() else directory


def available() -> list[str]:
    """CLIs that have a fixture directory with a manifest."""
    if not FIXTURE_ROOT.is_dir():
        return []
    return sorted(
        p.parent.name for p in FIXTURE_ROOT.glob(f"*/{MANIFEST_NAME}") if p.is_file()
    )


def measure(parser, limit_sessions: int = 6) -> Evidence:
    """Parse this CLI's fixture and count what survives. Touches no real store."""
    cli = parser.cli
    evidence = Evidence(cli=cli, present=cli_dir(cli).is_dir())
    data = manifest(cli)
    evidence.source_messages = int(data.get("source_messages") or 0)
    evidence.sampled = bool(data.get("sampled_records"))
    if not evidence.present:
        return evidence
    evidence.files = sum(1 for p in cli_dir(cli).rglob("*") if p.is_file())
    target = root_for(cli)
    reaim = getattr(parser, "with_root", None)
    if target is None or reaim is None:
        evidence.error = "fixture has no root, or the parser cannot be re-aimed"
        return evidence
    try:
        scoped = reaim(target)
        codec = getattr(scoped, "codec_ok", None)
        if callable(codec) and not codec():
            evidence.codec_missing = True
            evidence.error = "optional codec not installed; this store cannot be read here"
            return evidence
        metas = scoped.list_sessions()
        evidence.sessions = len(metas)
        for meta in metas[:limit_sessions]:
            raw = scoped.load(meta.session_id)
            if raw is None:
                evidence.error = f"{meta.session_id} is listed but does not load"
                continue
            evidence.messages += len(raw.messages)
            evidence.nonempty += sum(1 for m in raw.messages if m.text.strip())
            evidence.tools += sum(raw.tool_counts.values())
            evidence.files_touched += len(raw.files_touched)
    except (OSError, ValueError) as exc:
        evidence.error = f"{type(exc).__name__}: {exc}"
    return evidence


def tree_bytes(cli: str) -> int:
    directory = cli_dir(cli)
    if not directory.is_dir():
        return 0
    return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())

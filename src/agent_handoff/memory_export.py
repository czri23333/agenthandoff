"""Export what the local agent CLIs have been told to remember.

Session handoff covers *what was done*; this covers *what was agreed*: the
standing instructions and memory files that each coding CLI keeps outside any
single session (Claude Code's CLAUDE.md, Codex's global AGENTS.md, a project's
own AGENTS.md/CLAUDE.md, and so on). One command gathers every source it knows
about, renders the standard five-section dated format (English or Chinese),
and states plainly what it could not read.

The honesty rules are the contract, not a nicety:

- A store that does not exist on this machine is reported as skipped, never
  silently dropped and never pretended to be empty. An existing-but-empty
  file gets its own label ("file is empty") so "read, 0 entries" is never
  ambiguous.
- A file that exists but cannot be read is reported as unreadable.
- Dates come from the file's modification time, rendered in UTC so the
  output does not depend on which machine produced it. That is "last
  edited", not "first written", and the output says so. Entries with no
  date are ``[unknown]``. Guessing is forbidden.
- An empty section says the store held nothing of that kind; it never
  fabricates filler.
- Classification is a keyword heuristic and is labelled as such in the
  output; categories are guidance for a reader, not a claim about provenance.
- The secret scan reports *where* a hit is (label, offset, length) and never
  echoes the matched text: printing even a prefix of a real credential to a
  terminal or log would create a second copy of it.

Markdown files are split into list items (indented continuations merge into
their parent bullet). Plain text keeps whole non-blank lines. TOML/JSON config
files are counted as scanned but not parsed into entries - the honesty bar for
"we understood this file" is higher than "we opened it".
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import tomllib

# Budgets for untrusted input (the memory files themselves): a runaway file
# must not balloon the export or the scan. See docs/research.md item 15.
MAX_FILE_BYTES = 1_048_576
MAX_ENTRY_CHARS = 4_000
MAX_ENTRIES_PER_FILE = 400

CATEGORIES = ("instructions", "identity", "career", "projects", "preferences")

# The five-section format is language-neutral; these are its two local faces.
HEADINGS = {
    "en": {c: c for c in CATEGORIES},
    "zh": {
        "instructions": "指令",
        "identity": "身份",
        "career": "职业",
        "projects": "项目",
        "preferences": "偏好",
    },
}
EMPTY_NOTES = {
    "en": "(nothing of this kind was found in the scanned stores)",
    "zh": "（扫描到的存储中无此类信息）",
}

# Patterns that should make a human pause before pasting the export anywhere.
# Deliberately narrow (vendor-prefixed keys, PEM blocks): high-entropy strings
# are NOT caught by design - false positives here are as unrecoverable as
# false negatives are dangerous, and this scan is a courtesy flag, not a
# sanitizer. See docs/research.md item 14.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "vendor api key",
        re.compile(r"\b(?:sk|ghp|gho|ghs|ghu|xox[baprs]|AIza)[-_]?[0-9A-Za-z]{16,}"),
    ),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{12,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("url credentials", re.compile(r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^:/\s]+:[^@\s]+@")),
)


@dataclass(frozen=True)
class MemorySource:
    """One place a CLI keeps standing instructions. Paths are home-relative."""

    cli: str
    rel_paths: tuple[str, ...]
    kind: str  # markdown | text | config
    note: str = ""


# Registered from what we actually know about each CLI's layout. Nothing in
# this table is aspirational: a row exists because the location is documented
# by the vendor or was observed on a real machine. Machines differ, and the
# scan report - not this table - is the source of truth for what was read.
SOURCES: tuple[MemorySource, ...] = (
    MemorySource(
        "claude",
        (".claude/CLAUDE.md",),
        "markdown",
        "user-level memory; project-level files are read via --project",
    ),
    MemorySource("codex", (".codex/AGENTS.md",), "markdown", "global instructions"),
    MemorySource("gemini", (".gemini/GEMINI.md",), "markdown", "user-level context"),
    MemorySource(
        "kimi-code",
        (".kimi-code/config.toml",),
        "config",
        "config only; Kimi Code keeps no separate memory file we can parse",
    ),
    MemorySource(
        "zcode",
        (".zcode/cli/config.json",),
        "config",
        "config only; no parseable memory file is known for zcode",
    ),
)

PROJECT_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")


def known_clis() -> list[str]:
    """Every cli id `--cli` accepts, in registration order."""
    return [s.cli for s in SOURCES]


@dataclass(frozen=True)
class Entry:
    source: str
    path: str
    date: str  # YYYY-MM-DD or "unknown"
    category: str
    text: str


@dataclass(frozen=True)
class SourceReport:
    cli: str
    path: str
    status: str  # read | missing | unreadable | oversized | config-noted
    entries: int
    detail: str = ""


def _read_text(path: Path) -> tuple[str | None, str]:
    if path.stat().st_size > MAX_FILE_BYTES:
        return None, f"over the {MAX_FILE_BYTES}-byte budget; skipped"
    try:
        return path.read_text(encoding="utf-8", errors="replace"), ""
    except OSError as exc:
        return None, f"unreadable ({exc.__class__.__name__})"


_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def split_markdown_entries(text: str) -> list[str]:
    """List items are entries; an indented non-bullet line continues the one above."""
    entries: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if _BULLET_RE.match(line):
            entries.append(_BULLET_RE.sub("", line, count=1).strip())
        elif line.startswith((" ", "\t")) and entries:
            entries[-1] = f"{entries[-1]} {line.strip()}"
        else:
            # Headings and loose prose: keep them, they still carry instructions.
            entries.append(line.strip().lstrip("#").strip())
    return [e[:MAX_ENTRY_CHARS] for e in entries if e][:MAX_ENTRIES_PER_FILE]


def split_text_entries(text: str) -> list[str]:
    return [line.strip()[:MAX_ENTRY_CHARS] for line in text.splitlines() if line.strip()][
        :MAX_ENTRIES_PER_FILE
    ]


_PREF_HINTS = (
    "prefer", "style", "tone", "language", "format", "always", "never",
    "do not", "don't", "must", "should", "rule", "禁止", "必须", "始终", "绝不",
    "偏好", "风格", "语气", "不要", "要求",
)
_PROJECT_HINTS = (
    "project", "repo", "codebase", "architecture", "stack", "milestone",
    "项目", "仓库", "架构", "技术栈", "里程碑",
)
_IDENTITY_HINTS = ("name", "location", "age", "姓名", "所在地", "年龄", "教育")
_CAREER_HINTS = ("job", "company", "role", "employer", "work at", "职位", "公司", "雇主")


def classify(text: str) -> str:
    """Keyword heuristic, checked in category-priority order. Labelled as a
    heuristic in the rendered output; never presented as provenance."""
    low = text.lower()
    if any(h in low for h in _IDENTITY_HINTS):
        return "identity"
    if any(h in low for h in _CAREER_HINTS):
        return "career"
    if any(h in low for h in _PROJECT_HINTS):
        return "projects"
    if any(h in low for h in _PREF_HINTS):
        return "instructions"
    return "preferences"


def scan_sources(
    home: Path | None = None,
    project: Path | None = None,
    cli: str | None = None,
) -> tuple[list[Entry], list[SourceReport]]:
    home = home or Path.home()
    entries: list[Entry] = []
    reports: list[SourceReport] = []

    for source in SOURCES:
        if cli and source.cli != cli:
            continue
        for rel in source.rel_paths:
            path = home / rel
            display = path.as_posix().replace(home.as_posix(), "~", 1)
            if not path.is_file():
                reports.append(SourceReport(source.cli, display, "missing", 0))
                continue
            if source.kind == "config":
                detail = _config_note(path)
                reports.append(
                    SourceReport(source.cli, display, "config-noted", 0, detail)
                )
                continue
            text, problem = _read_text(path)
            if text is None:
                status = "oversized" if "budget" in problem else "unreadable"
                reports.append(SourceReport(source.cli, display, status, 0, problem))
                continue
            date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            raw = (
                split_markdown_entries(text)
                if source.kind == "markdown"
                else split_text_entries(text)
            )
            detail = "file is empty" if not raw else ""
            for item in raw:
                entries.append(Entry(source.cli, display, date, classify(item), item))
            reports.append(SourceReport(source.cli, display, "read", len(raw), detail))

    if project is not None:
        for name in PROJECT_FILES:
            path = project / name
            if not path.is_file():
                reports.append(SourceReport("project", name, "missing", 0))
                continue
            text, problem = _read_text(path)
            if text is None:
                status = "oversized" if "budget" in problem else "unreadable"
                reports.append(SourceReport("project", name, status, 0, problem))
                continue
            date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            raw = split_markdown_entries(text)
            detail = "file is empty" if not raw else ""
            for item in raw:
                entries.append(Entry("project", name, date, classify(item), item))
            reports.append(SourceReport("project", name, "read", len(raw), detail))

    return entries, reports


def _config_note(path: Path) -> str:
    """Prove the config parses and name its top-level keys; never dump values."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return f"unreadable ({exc.__class__.__name__})"
    if len(raw) > MAX_FILE_BYTES:
        return f"over the {MAX_FILE_BYTES}-byte budget; skipped"
    try:
        if path.suffix == ".json":
            data = json.loads(raw.decode("utf-8", errors="replace"))
            keys = sorted(k for k in data if isinstance(k, str)) if isinstance(data, dict) else []
        else:
            data = tomllib.loads(raw.decode("utf-8", errors="replace"))
            keys = sorted(data)
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        return f"present but unparsable ({exc.__class__.__name__})"
    return f"parsed; top-level keys: {', '.join(keys[:12])}" if keys else "parsed; empty"


def scan_secrets(text: str) -> list[dict[str, int | str]]:
    """Locate likely secrets WITHOUT echoing them.

    Returns label/offset/length triples. The matched text deliberately never
    appears in the result: printing even a prefix would create a second copy
    of the credential in a terminal scrollback or a log.
    """
    hits: list[dict[str, int | str]] = []
    for label, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            hits.append(
                {"label": label, "offset": match.start(), "length": len(match.group(0))}
            )
            if len(hits) >= 20:
                return hits
    return hits


def _sorted_entries(entries: list[Entry]) -> list[Entry]:
    """Earliest first; [unknown] sorts with the oldest because an unknown
    date is an admission, not a timestamp."""
    return sorted(entries, key=lambda e: ("" if e.date == "unknown" else e.date, e.text))


def _completeness_lines(reports: list[SourceReport], lang: str) -> list[str]:
    read_count = sum(1 for r in reports if r.status == "read")
    if lang == "zh":
        if not reports:
            first = "没有可扫描的来源。"
        else:
            first = (
                f"已读取 {read_count}/{len(reports)} 个已知来源；其余在上方列为缺失或不可读"
                "——它们是被跳过，不是空。"
            )
        second = (
            "日期为文件修改时间（UTC，即“最后编辑”），不是创建时间；无日期的条目为 [unknown]。"
            "分类是关键词启发式，不是出处证明。本导出只覆盖常驻指令文件"
            "——不含会话转写，也不含任何存在服务端的内容。"
        )
    else:
        if not reports:
            first = "no known sources were scanned."
        else:
            first = (
                f"{read_count}/{len(reports)} known sources were read; the rest are listed above "
                "as missing or unreadable — they were skipped, not empty."
            )
        second = (
            "Dates are file modification times in UTC (last edited), not creation times; "
            "entries without one are [unknown]. Categories are a keyword heuristic, "
            "not provenance. This export covers standing-instruction files only — "
            "it does not include session transcripts or anything stored server-side."
        )
    return [first, second]


def render(entries: list[Entry], reports: list[SourceReport], lang: str = "en") -> str:
    headings = HEADINGS[lang]
    lines = [
        "# 记忆导出（agenthandoff）" if lang == "zh" else "# Memory export (agenthandoff)",
        "",
    ]
    for category in CATEGORIES:
        lines.append(f"## {headings[category]}")
        lines.append("")
        bucket = _sorted_entries([e for e in entries if e.category == category])
        if not bucket:
            lines.append(f"- {EMPTY_NOTES[lang]}")
        for e in bucket:
            lines.append(f"- [{e.date}] ({e.source} `{e.path}`) - {e.text}")
        lines.append("")

    lines.append("## 扫描的来源" if lang == "zh" else "## sources scanned")
    lines.append("")
    for r in reports:
        detail = f" — {r.detail}" if r.detail else ""
        count = f", {r.entries} entries" if r.status == "read" else ""
        lines.append(f"- {r.cli}: `{r.path}` — {r.status}{count}{detail}")
    lines.append("")

    flags = scan_secrets("\n".join(e.text for e in entries))
    if flags:
        heading = "## 密钥扫描（只标记，不脱敏）" if lang == "zh" else "## secret scan (flag-only)"
        lines.append(heading)
        lines.append("")
        for f in flags:
            lines.append(
                f"- {f['label']}: offset {f['offset']}, {f['length']} chars (content withheld)"
            )
        lines.append("")

    lines.append("## 完整性" if lang == "zh" else "## completeness")
    lines.append("")
    lines.extend(_completeness_lines(reports, lang))
    return "\n".join(lines) + "\n"


def export_markdown(
    home: Path | None = None,
    project: Path | None = None,
    cli: str | None = None,
    lang: str = "en",
) -> str:
    entries, reports = scan_sources(home=home, project=project, cli=cli)
    return render(entries, reports, lang=lang)


def export_json(
    home: Path | None = None,
    project: Path | None = None,
    cli: str | None = None,
) -> dict:
    """Machine-readable twin of the markdown export. Same honesty contract:
    skipped sources stay visible in `reports`, and secret flags carry no text."""
    entries, reports = scan_sources(home=home, project=project, cli=cli)
    blob = "\n".join(e.text for e in entries)
    return {
        "entries": [asdict(e) for e in _sorted_entries(entries)],
        "reports": [asdict(r) for r in reports],
        "secret_flags": scan_secrets(blob),
        "completeness": {
            "read": sum(1 for r in reports if r.status == "read"),
            "total": len(reports),
        },
    }

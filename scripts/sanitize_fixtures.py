"""Generate structure-preserving, content-replaced fixtures from the live stores.

Why this exists. Every ✅ in the README used to mean "the maintainer's machine
could read it" — a claim nobody else can check, and one that already drifted into
a false statement once (Codex listed as stable while unreadable). A fixture in
this repo turns the claim into `pytest`: clone, run, see it.

Rules that make a fixture both useful and safe:

  * STRUCTURE IS PRESERVED — keys, nesting, record types, enum vocabulary, field
    types, id shapes, file layout. The point is to keep the *format* under test:
    synthetic files only verify the format we imagine, which is exactly how a
    vendor field rename slips through "passing" tests.
  * CONTENT IS REPLACED — every free-text leaf becomes generated text of the same
    character class and comparable length. No original wording survives.
  * PATHS / URLS / EMAILS / SECRETS ARE SYNTHESISED or redacted; timestamps stay
    (they are structure: ordering, windows, budgets).
  * AUDIT IS PART OF GENERATION — the run fails if the sanitized tree stops
    parsing, loses shape, or still contains a home path / username fragment.

Fixture layout per CLI (what gets handed to Parser.with_root()):

    tests/fixtures/sanitized/zcode/db.sqlite          -> the file itself
    tests/fixtures/sanitized/<jsonl family>/…         -> mirrors <home>/projects
    tests/fixtures/sanitized/dsh/…                    -> mirrors ~/.dsh/sessions
    tests/fixtures/sanitized/kimi/…                   -> mirrors ~/.kimi-code/sessions
    tests/fixtures/sanitized/codex/{sessions/…,session_index.jsonl}
                                          -> with_root(.../codex/sessions)

Usage:
    python scripts/sanitize_fixtures.py                 # regenerate everything
    python scripts/sanitize_fixtures.py --cli codex     # one CLI
    python scripts/sanitize_fixtures.py --audit         # verify, no rewriting
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import random
import re
import sqlite3
import sys
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_handoff.parsers import all_parsers  # noqa: E402

try:  # optional codec, exactly as in the library
    import zstandard
except ImportError:  # pragma: no cover
    zstandard = None

REPO = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO / "tests" / "fixtures" / "sanitized"
SEED = 20260831
MAX_TEXT = 300  # length class, not the words: a fixture is not an archive
SESSIONS_PER_CLI = 3
MAX_RECORDS = 200  # a fixture is a SAMPLE of a session, and says so
CANDIDATE_POOL = 60  # ranking 451 sessions means 451 full parses
HEAD_RECORDS = 60  # opening metadata, then a stride, then the newest record
MAX_FILE_BYTES = 200_000_000  # a dsh roll is 30 MB compressed; repo cost is lines
MAX_ROWS_PER_TABLE = 200  # a SQLite fixture keeps the schema, not the store
MAX_CLI_BYTES = 4_000_000  # 125 MB of fixtures is not a test fixture

# Field values that are schema rather than speech: kept verbatim so the fixture
# still drives the same code paths (types, roles, tools, statuses).
_ENUM_KEYS = {
    "type",
    "role",
    "kind",
    "status",
    "version",
    "mode",
    "level",
    "priority",
    "event",
    "channel",
    "os",
    "platform",
    "shell",
    "sandbox_mode",
    "approval_policy",
    "reason",
    "thread_source",
}
_ENUM_VALUE_MAX = 48

# Key names that carry vocabulary rather than speech. Guessed here; for SQLite the
# real domain comes from the CHECK constraints (see _check_vocabulary), which is
# what actually broke the first zcode rebuild.
_ENUM_KEY_RE = re.compile(
    r"(?:^|_)(type|kind|source|status|mode|role|state|direction|origin|version"
    r"|channel|level|priority|policy|adapter|format|scheme|reason|role|source)"
    r"(?:s|_id)?$",
    re.I,
)
_CHECK_RE = re.compile(r"(\w+)\s+in\s*\(([^)]*)\)", re.I)

# Structural prefixes parsers branch on; preserved so the fixture keeps exercising
# the same filter (and so sanitisation cannot accidentally "fix" a noise bug).
_MARKERS = (
    "<task-notification",
    "<environment_context",
    "<codex_internal_context",
    "<conversation_history_summary",
    "<user_instructions",
    "<goal_round",
    "# AGENTS.md instructions",
    "<app-context>",
    "<system-reminder",
    "<local-command",
    "<loaded_context",
    "<project_context",
    "Caveat:",
    "[Request interrupted",
    "<INSTRUCTIONS>",
)

_HEX_RE = re.compile(r"^[0-9a-fA-F]{8,64}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_IDISH_RE = re.compile(r"^[0-9A-Za-z_\-]{12,64}$")
_PATH_RE = re.compile(r"(^[A-Za-z]:[\\/])|(^/)|(^[.]{1,2}[\\/])|(^[A-Za-z]:$)")
_URL_RE = re.compile(r"^https?://", re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_SECRET_RE = re.compile(r"^(sk|pk|ghp|gho|xox[baprs]|ya29)[_-][0-9A-Za-z]{8,}$")
_DATEISH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?(\.\d+)?$")
# A whole value that is one path, relative or absolute, without spaces.
_JSON_WRAP_RE = re.compile(r"^\s*[{[]")
_WHOLE_PATH_RE = re.compile(
    r"^[A-Za-z0-9_.\-~\u4e00-\u9fff]{1,60}(?:[\\/][A-Za-z0-9_.\-~ ()\[\]\u4e00-\u9fff]{0,60}){1,8}$"
)
# A path-shaped token inside a short line of text.
_REL_PATH_RE = re.compile(
    r"[A-Za-z0-9_.\-~\u4e00-\u9fff]{2,}(?:[\\/][A-Za-z0-9_.\-~ ()\[\]\u4e00-\u9fff]{0,40}){1,6}"
)
_NAMEY_RE = re.compile(
    r"[\w.\-~]+\.(jsonl|json|md|py|ts|tsx|rs|toml|sqlite|db|txt|log|sh|ps1|zip|png|jpg)\b"
)

VOWELS = "aeiou"
CONSONANTS = "bcdfghjklmnpqrstvwxyz"
CJK = "项目文件会话上下文代码测试请求响应数据结果分析处理系统配置任务记录索引结构逻辑接口实现"

# Where the mirrored tree starts, per CLI: some parsers read siblings of root.
MIRROR_FROM_PARENT = {"codex"}


# Names the parsers locate by literally; everything else in a path is identity.
STATIC_NAMES = {
    "session.jsonl",
    "state.json",
    "wire.jsonl",
    "session_index.jsonl",
    "subagents",
    "logs",
    "todos",
    "tool-results",
    "sessions",
    "projects",
    "agents",
    "main",
    "compression-v2",
    "memory",
    "db.sqlite",
    # dsh rolls: `session.jsonl.zstd` is located by name, so it cannot be hashed
    # (the first dsh fixture listed 0 sessions for exactly this reason).
    "session.jsonl.zstd",
    "session.jsonl.zst",
    "meta.json",
}

# Prefixes parsers glob on; the identity after them may still be hashed.
_SEGMENT_PREFIXES = ("wd_", "session_", "rollout-", "agent-", "project_")

_HEXISH_RE = re.compile(r"^[0-9a-fA-F][0-9a-fA-F_-]{5,63}(\.[a-z0-9]{1,6})?$")


def _is_static_shape(segment: str) -> bool:
    """Keep a segment only when it is an id/uuid shape.

    Hex/uuid names are the parser's handle on a file and carry nothing personal
    (records referring to them are rewritten with the same mapping). Everything
    else - notably munged working paths such as `C--Users-c-zh`, which look
    innocuous at a glance - is a location or an account, and becomes a hash.
    """
    return bool(_HEXISH_RE.match(segment) or _UUID_RE.match(segment))


def _username_forms() -> set[str]:
    """The account name and the spellings vendors mangle it into.

    A store that rewrites `C:\\Users\\c'zh` into `C--Users-c-zh` keeps naming the
    same account, so a literal-name check is not a check. The scrubber and the
    audit read this ONE set; two lists that drift apart is how a green gate ends
    up sitting on top of a leak.
    """
    user = Path.home().name
    forms = {user, re.sub(r"[^0-9A-Za-z]", "-", user), re.sub(r"[^0-9A-Za-z]", "_", user)}
    return {f for f in forms if len(f) >= 4}  # shorter forms collide with prose


# Workspace names are collected from the live store before any fixture is
# written: `引擎3.1.1` identifies a person's project as surely as their account
# does, and no static pattern can guess it.
PROJECT_NEEDLES: set[str] = set()


def project_needles_for_path(cwd: str) -> set[str]:
    """Forms of a real working directory that must not survive sanitisation.

    The full path, the vendor-munged path, and the leaf - but the leaf only when
    it is distinctive. A cwd ending in `default` would otherwise publish that
    word as a needle, and the scrubber would then rewrite every
    `"status":"default"` in the store, which is how the zcode fixture lost all of
    its messages.
    """
    cwd = (cwd or "").strip().rstrip("\\/")
    if len(cwd) < 5:
        return set()
    out = {cwd, re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "-", cwd)}
    leaf = re.split(r"[\\/]+", cwd)[-1]
    if leaf.lower() in _STOP_LEAVES:
        return out
    distinctive = any(ch.isdigit() for ch in leaf) or any(
        "\u4e00" <= ch <= "\u9fff" for ch in leaf
    )
    long_enough_to_be_a_name = leaf.isascii() and leaf.isalpha() and len(leaf) >= 9
    if (distinctive and len(leaf) >= 5) or long_enough_to_be_a_name:
        out.add(leaf)
    return out


def note_project_path(cwd: str) -> None:
    """Register one real working directory so the scrubber can never miss it."""
    PROJECT_NEEDLES.update(project_needles_for_path(cwd))


def _scrub_patterns() -> list[re.Pattern[str]]:
    """Anything that must never appear in a fixture, at ANY position in a string.

    The tail class allows backslashes and apostrophes: stopping at either used to
    replace only the drive of `C:\\Users\\c'zh\\...` and leave the real path body
    behind. Over-eating prose is acceptable here, under-eating is not.
    """
    tail = r"[^\s,;\"')]*"
    names = _username_forms() | PROJECT_NEEDLES
    patterns = [
        re.compile(re.escape(str(Path.home())), re.I),
        re.compile(r"[A-Za-z]:[\\/]{1,2}" + tail),
        re.compile(
            r"(?:/{1,2}|[A-Za-z]:[\\/]{1,2})(?:home|users|mnt|volumes|root)/" + tail, re.I
        ),
        # vendor-munged absolute paths: `D--proj-x`, `C--Users-c-zh-...`
        re.compile(r"[A-Za-z]--[A-Za-z0-9_.\-]{2,}" + tail),
        # a profile segment inside a path. Lookarounds, not capture groups, and
        # no `"` as a delimiter: matching `"user"` inside `{"role":"user"` both
        # destroyed the role and blocked the embedded-JSON recursion above.
        re.compile(
            r"(?<=[\\/\-])(?:users?|home|var|mnt|volumes|documents?|desktop|downloads|appdata)"
            r"(?=[\\/\-])",
            re.I,
        ),
        # every spelling of the account and of this machine's projects
        re.compile(
            "|".join(sorted((re.escape(n) for n in names if len(n) >= 4), key=len, reverse=True))
            or "(?!)",
            re.I,
        ),
    ]
    return patterns


class Sanitizer:
    """Deterministic content replacer. Same seed, same store, same fixture bytes."""

    def __init__(self, salt: str) -> None:
        self.rng = random.Random(f"{SEED}:{salt}")
        self.ids: dict[str, str] = {}
        self.paths: dict[str, str] = {}
        self.redacted: list[str] = []
        self.scrub = _scrub_patterns()
        self.scrubbed = 0
        # Vocabulary learned from the schema: values that a CHECK constraint
        # enumerates must survive verbatim, or the rebuilt store violates it.
        self.keep: dict[str, set[str]] = {}

    def _clean(self, out: str) -> str:
        def _hide(match: re.Match[str]) -> str:
            return "syn-" + hashlib.sha1(match.group(0).encode()).hexdigest()[:8]

        for pattern in self.scrub:
            replaced = pattern.sub(_hide, out)
            if replaced != out:
                self.scrubbed += 1
                out = replaced
        return out

    def _word(self, english: bool) -> str:
        if english:
            n = self.rng.randint(3, 9)
            letters = "".join(
                self.rng.choice(CONSONANTS if i % 2 == 0 else VOWELS) for i in range(n)
            )
            return letters
        return "".join(self.rng.choice(CJK) for _ in range(self.rng.randint(2, 8)))

    def _prose(self, text: str) -> str:
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        want = max(2, min(len(text), MAX_TEXT))
        out: list[str] = []
        size = 0
        while size < want:
            english = cjk == 0 or self.rng.random() > (cjk / max(1, len(text)))
            piece = self._word(english) + ("，" if not english and self.rng.random() < 0.3 else " ")
            out.append(piece)
            size += len(piece)
        body = "".join(out)[:want]
        return body.rstrip(" ，") + ("。" if cjk else ".")

    def fake_id(self, value: str) -> str:
        if value in self.ids:
            return self.ids[value]
        digest = hashlib.sha1(f"id:{value}".encode()).hexdigest()
        if _UUID_RE.match(value):
            fake = "-".join((digest[:8], digest[8:12], digest[12:16], digest[16:20], digest[20:32]))
        elif _HEX_RE.match(value):
            fake = digest[: len(value)]
        else:
            fake = f"{self._word(True)}{digest[: max(4, len(value) % 20)]}"
        self.ids[value] = fake
        return fake

    def fake_path(self, value: str) -> str:
        if value in self.paths:
            return self.paths[value]
        windows = bool(re.match(r"^[A-Za-z]:", value)) or "\\" in value
        sep = "\\" if windows else "/"
        parts = [p for p in re.split(r"[\\/]+", value) if p]
        if windows:
            head, parts = self.rng.choice(["C:", "D:"]), parts[1:] or ["dir"]
        else:
            head, parts = "", parts
        # `work`/`srv` anchors, then GENERATED segments: reusing the real ones kept
        # publishing `C:\work\Users\...\Documents\...` after the drive was hidden.
        # Only names the parser locates literally survive, and mapped session ids
        # survive as their fake twin so records still point at mirrored files.
        kept = STATIC_NAMES | {fake for fake in self.ids.values()}

        def segment(part: str) -> str:
            for sid, fake in self.ids.items():
                if len(sid) > 8 and sid in part:
                    return fake if part == sid else part.replace(sid, fake)
            return part if part in kept else self._word(True)

        parts = (["srv"] if not head else ["work"]) + [segment(p) for p in parts]
        leaf = parts[-1]
        if "." in leaf and not _is_static_shape(leaf):
            _stem, _dot, ext = leaf.rpartition(".")
            keep_ext = ext if 1 <= len(ext) <= 6 and ext.isascii() and ext.isalnum() else "dat"
            leaf = f"{self._word(True)}.{keep_ext}"
            parts[-1] = leaf
        fake = (head + sep if head else sep) + sep.join(parts)
        self.paths[value] = fake
        return fake

    def string(self, key: str, value: str) -> str:
        if value in self.keep.get(key or "", ()):
            return value  # schema vocabulary: scrubbing it breaks the rebuild
        return self._clean(self._string(key, value))

    def _string(self, key: str, value: str) -> str:
        if not value:
            return value
        low = key.lower()
        if key in _ENUM_KEYS and len(value) <= _ENUM_VALUE_MAX and not re.search(r"\s", value):
            return value
        if (
            _ENUM_KEY_RE.search(key or "")
            and len(value) <= _ENUM_VALUE_MAX
            and not re.search(r"\s", value)
        ):
            return value
        for allowed in self.keep.get(key or "", ()):
            if value == allowed:
                return value
        if (
            _SECRET_RE.match(value)
            or "key" in low
            or "token" in low
            or "password" in low
            or "secret" in low
        ):
            self.redacted.append(key)
            return f"REDACTED-{hashlib.sha1(value.encode()).hexdigest()[:12]}"
        if _EMAIL_RE.match(value):
            return (
                f"person{int(hashlib.md5(value.encode()).hexdigest()[:4], 16) % 977}@example.test"
            )
        if _URL_RE.match(value):
            tail = re.sub(r"^https?://[^/]+/?", "", value)
            return (
                "https://example.test/"
                + "/".join(self._word(True) for _ in range(2))
                + ("/" + self._word(True) if tail else "")
            )
        if _DATEISH_RE.match(value) or _TIME_RE.match(value):
            return value
        if _JSON_WRAP_RE.match(value):
            # A string that is itself a record (`message.data`, `payload`,
            # `arguments`): sanitise it field by field so roles, tool names and
            # nesting survive. Flattening it to prose - which the old ordering
            # did - erased the very format the fixture is meant to test.
            try:
                inner = json.loads(value)
            except ValueError:
                inner = None
            if isinstance(inner, (dict, list)):
                return json.dumps(self.value(None, inner), ensure_ascii=False)
        if _UUID_RE.match(value) or (_IDISH_RE.match(value) and not _NAMEY_RE.search(value)):
            return self.fake_id(value)
        pathish = (
            _PATH_RE.match(value)
            or _WHOLE_PATH_RE.match(value.strip())
            or ("\\" in value and len(value) < 200)
            or (len(value) <= 200 and "\\n" not in value and _NAMEY_RE.search(value))
        )
        if pathish:
            return self._maybe_embedded_paths(value)
        stripped = value.lstrip()
        for marker in _MARKERS:
            if stripped.startswith(marker):
                cut = value.find(">")
                if 0 < cut < 80:
                    return value[: cut + 1] + self._prose(value[cut + 1 :] or "note")
                return marker + " " + self._prose(value[len(marker) :] or "note")
        return self._prose(value)

    def _maybe_embedded_paths(self, value: str) -> str:
        """Keep the shape of a path-ish string, replacing each real segment."""
        stripped = value.strip()
        if _PATH_RE.match(stripped) and "\n" not in value:
            return self.fake_path(stripped)
        # Relative paths (`games/chuhua/scene/1.txt`) are the ones that leak: the
        # old pattern could not cross `/`, so it rewrote only the filename and
        # published the directory chain in front of it.
        return _REL_PATH_RE.sub(lambda m: self.fake_path(m.group(0)).replace("\\", "/"), value)

    def value(self, key: str | None, node):
        if isinstance(node, dict):
            # Keys carry data too: CodeBuddy's file-history snapshots use
            # absolute paths as dict keys, which slipped past a values-only pass.
            return {self.map_key(k): self.value(k, v) for k, v in node.items()}
        if isinstance(node, list):
            return [self.value(key, v) for v in node]
        if isinstance(node, str):
            out = self.string(key or "", node)
            if out == node and "{" in node and node.lstrip()[:1] in "{[":
                out = self.json_string(node)
            return out
        return node

    def name(self, value: str) -> str:
        """Sanitise a path segment: keep layout-signalling names, fake the rest.

        Project directories are munged working paths (`d-引擎3.1.1`, `--D--demo--`),
        so an unmapped segment can leak a real workspace name even when every
        string inside the records has been replaced.
        """
        if value in STATIC_NAMES or value in ("", ".", ".."):
            return value
        out = value
        for sid, fake in self.ids.items():
            if len(sid) > 8 and sid in out:
                out = out.replace(sid, fake)
        if out == value and not _is_static_shape(value):
            # Anything the parser does not locate literally identifies a place or a
            # person: hash it, but keep a structural prefix, because KimiParser
            # globs `wd_*/session_*/state.json` and a renamed directory makes the
            # fixture unparseable.
            prefix = next((p for p in _SEGMENT_PREFIXES if value.startswith(p)), "")
            stem, dot, ext = value.rpartition(".")
            token = "scope-" + hashlib.sha1(value.encode()).hexdigest()[:10]
            tail = f"{token}.{ext}" if dot and 1 <= len(ext) <= 6 else token
            out = prefix + tail
        return self._clean(out)


    def map_key(self, key: str) -> str:
        """A dict key is a string, and in these stores it can be a path."""
        if not isinstance(key, str) or not key:
            return key
        if key in _ENUM_KEYS or _ENUM_KEY_RE.search(key):
            return key  # field names are schema
        if _PATH_RE.search(key) or _NAMEY_RE.search(key) or "\\" in key or "/" in key:
            return self._clean(self.fake_path(key))
        return self._clean(key)


    def json_string(self, raw: str) -> str:
        """A string field that is itself JSON (tool arguments, encoded records)."""
        try:
            inner = json.loads(raw)
        except ValueError:
            return raw
        if not isinstance(inner, (dict, list)):
            return raw
        return json.dumps(self.value(None, inner), ensure_ascii=False)


# Records that carry a turn of the conversation, across every family here.
_DIALOGUE_RE = re.compile(
    r'"(?:type|role)"\s*:\s*"(?:user|assistant|user_message|agent_message|user/message'
    r'|assistant/chunk|response_item|function_call|function_call_output|message)"'
)


def _stride(picks: list[int], budget: int) -> list[int]:
    """Evenly spaced indices, so the early and the late part both survive."""
    if len(picks) <= budget:
        return list(picks)
    step = max(1, len(picks) // max(1, budget))
    return picks[::step][:budget]


def _sample_lines(lines: list[str]) -> tuple[list[str], bool]:
    """Keep the head, the newest record, and enough dialogue to matter.

    Positional sampling is what made the dsh fixture empty: dialogue is ~0.3% of
    a 107k-line roll, so a 1-in-500 stride keeps almost none of it. Choosing by
    record kind keeps the turns AND a spread of the surrounding metadata, and the
    original order survives because indices are sorted before use.
    `sampled` is reported in .fixture.json so a fixture can never be mistaken for
    a complete transcript.
    """
    if len(lines) <= MAX_RECORDS:
        return lines, False
    head = lines[:HEAD_RECORDS]
    tail = lines[-1:]
    rest = lines[HEAD_RECORDS:-1]
    budget = max(1, MAX_RECORDS - len(head) - len(tail))
    flags = [bool(_DIALOGUE_RE.search(ln[:400])) for ln in rest]
    dialogue = [i for i, hit in enumerate(flags) if hit]
    other = [i for i, hit in enumerate(flags) if not hit]
    kept_dialogue = _stride(dialogue, max(1, budget * 6 // 10))
    keep = set(kept_dialogue) | set(_stride(other, max(1, budget - len(kept_dialogue))))
    picked = [rest[i] for i in sorted(keep)]
    return head + picked[:budget] + tail, True


def transform_jsonl(data: bytes, san: Sanitizer) -> tuple[bytes, bool]:
    out: list[str] = []
    kept, sampled = _sample_lines(
        [ln for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    )
    for line in kept:
        try:
            obj = json.loads(line)
        except ValueError:
            # Logs and malformed lines are pure content: passing them through
            # verbatim once shipped 100+ real home paths inside a codex .log.
            # The line COUNT and its leading timestamp are the format contract.
            out.append(_line_as_prose(line, san))
            continue
        if isinstance(obj, dict):
            obj = {k: san.value(k, v) for k, v in obj.items()}
        out.append(json.dumps(obj, ensure_ascii=False))
    return ("\n".join(out) + "\n").encode("utf-8"), sampled


_TS_PREFIX_RE = re.compile(r"^\s*[\[\(]?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}[^\]\s]*[\]\)]?\s*")


def _line_as_prose(line: str, san: Sanitizer) -> str:
    """Same line count, same timestamp, no original wording.

    `log` records exist in these stores and a parser may glob for them, so the
    fixture keeps them - but a log line is free text, and free text is exactly
    what a fixture must not carry.
    """
    stamp = _TS_PREFIX_RE.match(line)
    head = stamp.group(0) if stamp else ""
    return head + san.string("text", line[len(head) :] or "note")


def transform_json(data: bytes, san: Sanitizer) -> bytes:
    try:
        obj = json.loads(data.decode("utf-8", errors="replace"))
    except ValueError:
        # A .json file that is not JSON is still content; never copy it raw.
        return transform_jsonl(data, san)[0]
    return json.dumps(san.value(None, obj), ensure_ascii=False, indent=2).encode("utf-8")


def _zstd_decompress(data: bytes) -> bytes:
    """Read every frame of a roll.

    Vendor rolls carry no content-size header (so plain `decompress()` fails) and
    dsh appends one frame per record group, so `decompressobj().decompress()`
    stops after the first frame - a 30 MB session became 157 bytes. This is the
    same call DshParser makes: the generator has to read the store the way the
    library does, or it sanitises a file that does not exist.
    """
    import io

    reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data))
    return reader.read()


def _check_vocabulary(sql: str) -> dict[str, set[str]]:
    """Column -> allowed values, read out of a table's CHECK constraints.

    A fixture must reproduce the constrained domain, not invent a new one: the
    first zcode rebuild failed on `title_source in ('default','first_input',...)`
    because the sanitizer had replaced those values with generated prose.
    """
    out: dict[str, set[str]] = {}
    for column, raw in _CHECK_RE.findall(sql):
        values = {v.strip().strip("'\"") for v in raw.split(",")}
        values = {v for v in values if v and not v.isdigit()}
        if values:
            out.setdefault(column.lower(), set()).update(values)
    return out


def _session_column(source: sqlite3.Connection, name: str) -> str | None:
    """The column that ties a table row to one session, when the store has one."""
    cols = [r[1] for r in source.execute(f'PRAGMA table_info("{name}")')]
    lowered = {c.lower(): c for c in cols}
    for candidate in ("session_id", "parent_session_id", "root_session_id", "chat_id"):
        if candidate in lowered:
            return lowered[candidate]
    if name.lower().rstrip("s") in {"session", "conversation", "thread", "chat"}:
        return lowered.get("id")
    return None


def transform_sqlite(src: Path, dst: Path, san: Sanitizer, sessions: list[str]) -> dict:
    """Rebuild the database: same schema, sanitized text, chosen sessions only.

    The first version copied every row of every table, so the zcode fixture
    carried all 223 of the maintainer's sessions - other projects, other paths,
    125 MB. Row counts are capped per table and the cap is reported in the
    manifest, so a fixture states what it is a sample of.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    stats: dict = {"rows": 0, "tables": 0, "capped": [], "unfiltered": [], "empty": []}
    con = sqlite3.connect(dst)
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source:
        schema = list(
            source.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL")
        )
        for _typ, _name, sql in schema:
            con.execute(sql)
        for typ, name, sql in schema:
            if typ != "table" or name.startswith("sqlite_"):
                continue
            san.keep = {k.lower(): set(v) for k, v in _check_vocabulary(sql or "").items()}
            cols = [r[1] for r in source.execute(f'PRAGMA table_info("{name}")')]
            if not cols:
                continue
            stats["tables"] += 1
            quoted = ",".join(f'"{c}"' for c in cols)
            where, params = "", ()
            key = _session_column(source, name)
            if sessions and key:
                marks = ",".join("?" * len(sessions))
                where, params = f' WHERE "{key}" IN ({marks})', tuple(sessions)
            elif sessions:
                stats["unfiltered"].append(name)
            total = source.execute(f'SELECT COUNT(*) FROM "{name}"{where}', params).fetchone()[0]
            limit = ""
            if total > MAX_ROWS_PER_TABLE:
                limit = f" ORDER BY rowid LIMIT {MAX_ROWS_PER_TABLE}"
                stats["capped"].append(name)
            if total == 0 and key:
                stats["empty"].append(name)
            insert = f'INSERT INTO "{name}" ({quoted}) VALUES ({",".join("?" * len(cols))})'
            for record in source.execute(f'SELECT {quoted} FROM "{name}"{where}{limit}', params):
                values = [
                    san.value(col, v) if isinstance(v, str) else v
                    for col, v in zip(cols, record, strict=False)
                ]
                con.execute(insert, values)
                stats["rows"] += 1
    con.commit()
    con.close()
    san.keep = {}
    return stats


def _source_bytes(meta) -> int:
    """How big the store file behind a session is; 0 when unknown."""
    try:
        return Path(meta.source_path or "").stat().st_size
    except (OSError, ValueError):
        return 0


def pick_sessions(parser) -> tuple[list[str], int]:
    """The richest sessions, and how much dialogue they actually hold.

    A fixture of a two-turn session exercises almost nothing, and recency-based
    selection produced exactly that on the first run. Parsing every candidate is
    not an option either (a dsh roll decompresses to 68 MB), so file size ranks
    the candidates and only the top few are parsed. The returned source message
    count is what the audit later holds the fixture against.
    """
    metas = sorted(parser.list_sessions(), key=lambda m: m.updated_at or "", reverse=True)
    for meta in metas[:CANDIDATE_POOL]:
        note_project_path(meta.cwd or "")
    ranked = sorted(metas[:CANDIDATE_POOL], key=_source_bytes, reverse=True)
    scored: list[tuple[int, str]] = []
    for meta in ranked[: SESSIONS_PER_CLI * 4]:
        try:
            raw = parser.load(meta.session_id)
        except (OSError, ValueError):
            continue
        if raw is None:
            continue
        substance = len(raw.messages) + len(raw.files_touched) // 2
        scored.append((substance, meta.session_id))
    scored.sort(reverse=True)
    chosen = [sid for _score, sid in scored[:SESSIONS_PER_CLI]]
    if not chosen:
        # Best effort beats silence: a thin store still gets a fixture, and the
        # audit - not the selector - decides whether it is meaningful.
        chosen = [meta.session_id for meta in ranked[:SESSIONS_PER_CLI]]
    source_messages = 0
    for sid in chosen:
        try:
            raw = parser.load(sid)
        except (OSError, ValueError):
            raw = None
        source_messages += 0 if raw is None else len(raw.messages)
    return chosen, source_messages



def select_files(base: Path, root: Path, sessions: list[str]) -> list[Path]:
    """Store files backing the chosen sessions, plus their sibling records.

    A session is often spread over several files (kimi keeps `state.json` and
    `wire.jsonl` side by side, and only one of them contains the id), so whole
    directories that matched are taken intact - a half-copied session parses to
    nothing and would look like parser drift instead of a broken fixture.
    """
    if base.is_file():
        return [base]
    candidates = sorted(
        p for p in base.rglob("*") if p.is_file() and p.stat().st_size <= MAX_FILE_BYTES
    )
    if not candidates:
        return []
    matched_dirs: list[Path] = []
    wanted: list[Path] = []
    for sid in sessions:
        token = sid[:13] if len(sid) > 20 else sid
        hits = [
            p
            for p in candidates
            if sid in p.name or token in p.name or token in str(p.relative_to(base))
        ]
        if not hits:
            hits = [
                p for p in candidates if sid in p.read_bytes()[:40000].decode("utf-8", "ignore")
            ]
        for hit in hits:
            wanted.append(hit)
            matched_dirs.append(hit.parent)
    for directory in dict.fromkeys(matched_dirs):
        for sibling in sorted(directory.iterdir()):
            if (
                sibling.is_file()
                and sibling.stat().st_size <= MAX_FILE_BYTES
                and sibling not in wanted
            ):
                wanted.append(sibling)
    for p in candidates:  # small vendor indexes sit outside the session dirs
        if p.name in {"session_index.jsonl"} and p not in wanted:
            wanted.append(p)
    seen: set[Path] = set()
    return [p for p in wanted if not (p in seen or seen.add(p))][:24]


def write_fixture(cli: str, parser, sessions: list[str], source_messages: int) -> dict:
    root = Path(getattr(parser, "root", None) or parser.db_path)
    base = root.parent if cli in MIRROR_FROM_PARENT else root
    out_dir = OUT_ROOT / cli
    if out_dir.exists():
        for stale in sorted(out_dir.rglob("*"), reverse=True):
            if stale.is_file():
                stale.unlink()
    san = Sanitizer(cli)
    written: list[dict] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in select_files(base, root, sessions):
        data = src.read_bytes()
        name = src.name.lower()
        sampled = False
        # Two passes on purpose: transform FIRST (which is where session ids get
        # mapped), then derive the sanitized filename from the finished map.
        # Naming the file before transforming left real ids in filenames whose
        # records had already been remapped, so nothing could load.
        if name.endswith((".zstd", ".zst")):
            if zstandard is None:
                continue
            body, sampled = transform_jsonl(_zstd_decompress(data), san)
            payload = zstandard.ZstdCompressor().compress(body)
        elif name.endswith((".sqlite", ".db")):
            payload = None  # handled by the sqlite rebuilder below
        elif name.endswith(".jsonl"):
            payload, sampled = transform_jsonl(data, san)
        elif name.endswith(".json"):
            payload = transform_json(data, san)
        else:
            payload, sampled = transform_jsonl(data, san)

        rel = Path(
            *[
                san.name(part)
                for part in (Path(src.name) if base.is_file() else src.relative_to(base)).parts
            ]
        )
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        extra: dict = {}
        if payload is None:
            extra = {"sqlite": transform_sqlite(src, dst, san, sessions)}
        else:
            dst.write_bytes(payload)
        written.append(
            {"rel": str(rel), "bytes": dst.stat().st_size, "sampled": sampled, **extra}
        )
    # Record what a parser must be aimed at: the mirrored equivalent of the live
    # root (a directory for store-dir CLIs, the file itself for SQLite).
    if base.is_file():
        with_root_path = out_dir / base.name
    elif base == root:
        with_root_path = out_dir
    else:  # mirrored one level up (codex): root is a child of base
        with_root_path = out_dir / root.name
    with_root = str(with_root_path.relative_to(OUT_ROOT))
    (out_dir / ".fixture.json").write_text(
        json.dumps(
            {
                "cli": cli,
                "with_root": with_root,
                # shape only, never the real path - this file lives in the repo
                "mirrors": _portable(root),
                "sessions": [san.fake_id(s) if len(s) > 8 else s for s in sessions],
                "files": written,
                "redacted_keys": sorted(set(san.redacted)),
                "scrubbed_hits": san.scrubbed,
                "sampled_records": any(w["sampled"] for w in written),
                # What the SOURCE sessions held, so the fixture's fidelity is a
                # claim a reader can check rather than an impression.
                "source_messages": source_messages,
                "max_records": MAX_RECORDS,
                "candidate_pool": CANDIDATE_POOL,
                "seed": SEED,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "root": str(root),
        "base": str(base),
        "sessions": sessions,
        "files": written,
        "redacted": sorted(set(san.redacted)),
        "scrubbed": san.scrubbed,
    }


def _portable(path: Path) -> str:
    """A home-relative spelling, safe to commit (never an absolute local path)."""
    try:
        return "~/" + str(Path(path).relative_to(Path.home())).replace("\\", "/")
    except ValueError:
        return str(path).replace(str(Path.home()), "~").replace("\\", "/")


def fixture_root_for(cli: str) -> Path:
    """Where a parser must be aimed to read this CLI's fixture."""
    root = OUT_ROOT / cli
    meta = root / ".fixture.json"
    if meta.is_file():
        try:
            wanted = json.loads(meta.read_text(encoding="utf-8")).get("with_root")
            if wanted:
                return OUT_ROOT / wanted
        except ValueError:
            pass
    return root / "sessions" if cli in MIRROR_FROM_PARENT else root


# A path segment that only exists on a real machine. Matching a drive letter plus
# a separator does not work: in JSON, `e:` followed by an escaped newline looks
# exactly like `e:\...`, so the naive version reported ~100 false leaks.
_PERSONAL_SEGMENT_RE = re.compile(
    r"[\\/\-](?:users?|home|var|mnt|volumes|documents?|desktop|downloads|appdata)[\\/\-]",
    re.I,
)
# Leaves too generic to identify anybody; a fixture may legitimately say "projects".
_STOP_LEAVES = {
    "projects",
    "sessions",
    "agents",
    "workspace",
    "documents",
    "desktop",
    "downloads",
    "appdata",
}
_ZLIB_MAGIC = (b"\x78\x9c", b"\x78\x01", b"\x78\xda", b"\x1f\x8b")


def _manifest_field(cli: str, key: str, default=0):
    """Read one field of a fixture's own manifest ({} when there is none)."""
    meta = OUT_ROOT / cli / ".fixture.json"
    if not meta.is_file():
        return default
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get(key, default)
    except ValueError:
        return default


def _leak_needles() -> set[str]:
    """Home, plus every mangled spelling of the account name."""
    return {str(Path.home())} | _username_forms()


def _real_world_needles(parser) -> set[str]:
    """The live store's own project paths, plus the forms vendors mangle them into.

    The account name is not the only personal data here: `cwd` says which projects
    the person works on, and stores routinely re-encode it as a directory name
    (`D--proj-mygame`). Leaving those in a fixture would publish the work even
    after the username is gone, so they are audited too.
    """
    out: set[str] = set()
    try:
        metas = parser.list_sessions()
    except (OSError, ValueError):
        return out
    for meta in metas[:CANDIDATE_POOL]:
        out |= project_needles_for_path(meta.cwd or "")
    return out
    for meta in metas[:CANDIDATE_POOL]:
        cwd = (meta.cwd or "").strip().rstrip("\\/")
        if len(cwd) < 5 or cwd in str(Path.home()):
            continue
        out.add(cwd)
        out.add(re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "-", cwd))
        leaf = re.split(r"[\\/]+", cwd)[-1]
        if len(leaf) >= 5 and leaf.lower() not in _STOP_LEAVES:
            out.add(leaf)
    return out


def _leak_hits(blob: bytes, where: str = "", extra: tuple[str, ...] = ()) -> list[str]:
    """Why this byte string would not be safe to publish."""
    text = blob.decode("utf-8", "replace")
    lowered = text.lower()
    hits = [f"{where}needle {n!r}" for n in _leak_needles() if n.lower() in lowered]
    hits += [f"{where}project path {n!r}" for n in extra if n.lower() in lowered]
    match = _PERSONAL_SEGMENT_RE.search(text)
    if match:
        hits.append(f"{where}path segment {match.group(0)!r}")
    return hits


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', "") + '"'


def _try_inflate(raw: bytes) -> bytes | None:
    """Decompress a cell if it is compressed; the magic bytes are the test."""
    if raw[:2] not in _ZLIB_MAGIC:
        return None
    try:
        return zlib.decompress(raw)
    except Exception:  # a look-alike prefix, not a zlib stream
        return None


def _sqlite_cell_blobs(path: Path) -> list[tuple[str, bytes]]:
    """Every cell, so compression cannot hide a leak from the byte scan."""
    out: list[tuple[str, bytes]] = []
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        ]
        for name in tables:
            columns = [r[1] for r in con.execute(f"PRAGMA table_info({_quote(name)})")]
            if not columns:
                continue
            cols = ",".join(_quote(c) for c in columns)
            for row in con.execute(f"SELECT {cols} FROM {_quote(name)}"):
                for col, cell in zip(columns, row, strict=False):
                    if isinstance(cell, str):
                        out.append((f"{name}.{col}: ", cell.encode()))
                    elif isinstance(cell, (bytes, bytearray)):
                        raw = bytes(cell)
                        out.append((f"{name}.{col}(blob): ", raw))
                        inflated = _try_inflate(raw)
                        if inflated:
                            out.append((f"{name}.{col}(inflated): ", inflated))
    finally:
        con.close()
    return out


def _file_leaks(path: Path, extra: tuple[str, ...] = ()) -> list[str]:
    hits = _leak_hits(path.read_bytes(), where=f"{path.name}: ", extra=extra)
    if path.suffix.lower() in {".sqlite", ".db"}:
        try:
            cells = _sqlite_cell_blobs(path)
        except sqlite3.Error:
            return [f"{path.name}: unreadable sqlite fixture"]
        for where, payload in cells[:4000]:
            hits.extend(_leak_hits(payload, where=where, extra=extra))
    return sorted(set(hits))



def audit_cli(cli: str, parser) -> tuple[list[str], Counter]:
    fixture = fixture_root_for(cli)
    if not fixture.exists():
        return [f"{cli}: fixture missing ({fixture})"], Counter()
    try:
        scoped = parser.with_root(fixture)
    except (OSError, ValueError) as exc:
        return [f"{cli}: cannot aim parser: {exc}"], Counter()
    problems: list[str] = []
    metas = scoped.list_sessions()
    if not metas:
        return [f"{cli}: fixture lists 0 sessions (parser drift or bad mirror)"], Counter()
    shape: Counter = Counter()
    for meta in metas[:6]:
        raw = scoped.load(meta.session_id)
        if raw is None:
            problems.append(f"{cli}: {meta.session_id} did not load")
            continue
        shape["sessions"] += 1
        shape["messages"] += len(raw.messages)
        shape["nonempty"] += sum(1 for m in raw.messages if m.text.strip())
        shape["files"] += len(raw.files_touched)
        shape["tools"] += sum(raw.tool_counts.values())
        # Some stores legitimately keep empty "new session" rows: only the
        # aggregate matters, asserted by the nonempty check below.
        if not raw.meta.title:
            problems.append(f"{cli}: {meta.session_id} lost its title")
    source_messages = _manifest_field(cli, "source_messages")
    if shape["nonempty"] == 0:
        if source_messages:
            problems.append(
                f"{cli}: fixture is empty but the source sessions held "
                f"{source_messages} messages (sampling or mirroring lost them)"
            )
        else:
            # Honest gap: the store itself has no dialogue to sample.
            shape["shape_only"] = True
    extra = tuple(_real_world_needles(parser))
    for path in sorted(fixture.rglob("*")):
        if not path.is_file():
            continue
        for hit in _file_leaks(path, extra)[:8]:  # 8 per file is enough to act on
            problems.append(f"{cli}: LEAK {hit}")
    return problems, shape


def main() -> int:
    # A GBK console is the default on zh-CN Windows; printing a character it
    # cannot encode used to abort the whole audit mid-report, hiding every CLI
    # after the one that tripped it.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", action="append", help="restrict to these cli ids")
    ap.add_argument("--audit", action="store_true", help="verify existing fixtures only")
    args = ap.parse_args()

    failures = 0
    for parser in all_parsers():
        if args.cli and parser.cli not in args.cli:
            continue
        live = Path(getattr(parser, "root", None) or parser.db_path)
        if not args.audit:
            if not live.exists():
                print(f"[skip] {parser.cli:<14} no live store at {live}")
                continue
            sessions, source_messages = pick_sessions(parser)
            info = write_fixture(parser.cli, parser, sessions, source_messages)
            if not info["files"]:
                print(f"[skip] {parser.cli:<14} nothing selectable (0 readable sessions)")
                continue
        problems, shape = audit_cli(parser.cli, parser)
        out_dir = OUT_ROOT / parser.cli
        if out_dir.is_dir():
            total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
            shape["MB"] = round(total / 1e6, 2)
            shape["src_msgs"] = _manifest_field(parser.cli, "source_messages")
            if total > MAX_CLI_BYTES:
                problems.append(f"{parser.cli}: fixture is {total / 1e6:.1f} MB (> 4 MB)")
        failures += len(problems)
        print(f"[{'ok ' if not problems else 'FAIL'}] {parser.cli:<14} {dict(shape)}")
        for problem in problems:
            print(f"    ! {problem}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

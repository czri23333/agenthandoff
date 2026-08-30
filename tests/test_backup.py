"""Backup regression: the archive must never eat itself.

`handoff backup` writes into ~/.agenthandoff/backups/, while ~/.agenthandoff *is*
the global exchange directory it also copies - which previously produced
backups/backup-X/exchange_global/backups/backup-X/… until Windows refused the
path. These tests pin the fixed behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_handoff import backup as B
from agent_handoff.locations import StoreInfo


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A ~/.agenthandoff with a session store, a vault copy and an index cache."""
    monkeypatch.setattr(B.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(B, "discover", lambda: [])
    monkeypatch.setattr(B, "global_dir", lambda: tmp_path / ".agenthandoff")
    monkeypatch.setattr(B, "project_dir", lambda: tmp_path / "proj" / ".agenthandoff")

    state = tmp_path / ".agenthandoff"
    (state / "vault" / "zcode").mkdir(parents=True)
    (state / "vault" / "zcode" / "s1.json").write_text('{"ok": true}', encoding="utf-8")
    (state / "search-index.sqlite3").write_bytes(b"cache-not-data")
    (state / "domains.toml").write_text('[domains]\n"D:/x" = "y"\n', encoding="utf-8")
    (tmp_path / "proj" / ".agenthandoff").mkdir(parents=True)
    (tmp_path / "proj" / ".agenthandoff" / "bundle.md").write_text("# bundle\n", encoding="utf-8")
    return tmp_path


def _run() -> Path:
    return B.backup()


def test_backup_lands_under_agenthandoff(fake_home):
    dest = _run()
    assert dest.is_dir()
    assert (dest / "manifest.json").is_file()
    assert ".agenthandoff" in str(dest.parent)


def test_vault_and_exchange_are_archived_index_is_not(fake_home):
    dest = _run()
    vault_copy = dest / "exchange_global" / "vault" / "zcode" / "s1.json"
    assert vault_copy.is_file(), "the vault is the point of the whole archive"
    assert (dest / "exchange_project" / "bundle.md").is_file()
    assert not (dest / "exchange_global" / "search-index.sqlite3").exists(), "caches are not data"


def test_second_backup_does_not_recurse_into_the_first(fake_home):
    _run()
    second = _run()

    nested = [
        p for p in second.rglob("*") if "backups" in p.parts and p.parts.count("backups") > 1
    ]
    assert not nested, f"backup nested inside a backup: {[str(n) for n in nested[:2]]}"
    depth = max(len(p.parts) - len(Path(str(second)).parts) for p in second.rglob("*"))
    assert depth <= 4, f"path depth ran away: {depth}"


def test_store_copy_still_works(fake_home):
    store = fake_home / "store.jsonl"
    store.write_text('{"a": 1}\n', encoding="utf-8")
    monkey_store = StoreInfo("zcode", "sqlite", store, True, "1 session file(s)")
    import agent_handoff.backup as mod

    original = mod.discover
    mod.discover = lambda: [monkey_store]
    try:
        dest = _run()
    finally:
        mod.discover = original
    assert (dest / "stores" / "zcode__store.jsonl").is_file()
    manifest = (dest / "manifest.json").read_text(encoding="utf-8")
    assert "archived_files" in manifest


def test_manifest_records_the_session_shape(fake_home):
    dest = _run()
    text = (dest / "manifest.json").read_text(encoding="utf-8")
    assert "bundle_version" in text and "created_at" in text


def test_backup_does_not_modify_the_preexisting_source(fake_home):
    """Backing up is read-only apart from creating backups/ itself."""
    state = fake_home / ".agenthandoff"
    before = sorted(p.name for p in state.iterdir())
    _run()
    after = sorted(p.name for p in state.iterdir() if p.name != "backups")
    assert after == before

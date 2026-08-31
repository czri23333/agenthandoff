"""Leases and claim races: the coordination the exchange promises.

The behaviours asserted here are the ones whose absence stays invisible until two
agents are already working on the same handoff: a claim that can be won twice, a
lease that keeps blocking after its holder died, and a corrupt sidecar that
deadlocks the queue.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_handoff.exchange import (
    LEASE_SUFFIX,
    AlreadyClaimed,
    claim,
    inbox,
    lease,
    lease_of,
    publish,
    release,
)
from agent_handoff.model import HandoffBundle, SessionMeta
from agent_handoff.render import render_markdown


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bundle = HandoffBundle(
        meta=SessionMeta(cli="zcode", session_id="sess_lease1", title="lease me", cwd="D:/demo")
    )
    src = tmp_path / "bundle.md"
    src.write_text(render_markdown(bundle), encoding="utf-8")
    return publish(src, note="night shift")


def test_publish_with_lease_shows_it_in_the_inbox(tmp_path, published):
    lease(published, minutes=30, owner="agent-A")
    item = inbox()[0]
    assert item.leased
    assert item.lease_by == "agent-A"
    assert item.claimed is False


def test_a_live_lease_blocks_another_agent(published):
    lease(published, minutes=30, owner="agent-A")
    with pytest.raises(AlreadyClaimed) as caught:
        claim(published, claimed_by="agent-B")
    assert "agent-A" in str(caught.value)


def test_the_holder_may_claim_its_own_leased_handoff(published):
    lease(published, minutes=30, owner="agent-A")
    assert claim(published, claimed_by="agent-A").exists()


def test_an_expired_lease_blocks_nobody(published):
    sidecar = published.with_name(published.name + LEASE_SUFFIX)
    lease(published, minutes=30, owner="agent-A")
    stale = json.loads(sidecar.read_text(encoding="utf-8"))
    stale["until"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(
        timespec="seconds"
    )
    sidecar.write_text(json.dumps(stale), encoding="utf-8")
    assert lease_of(published) == {}
    assert inbox()[0].leased is False
    assert claim(published, claimed_by="agent-B").exists()


def test_a_second_claim_loses_the_race(published):
    claim(published, claimed_by="agent-A")
    with pytest.raises(AlreadyClaimed):
        claim(published, claimed_by="agent-B")
    marker = json.loads(
        published.with_name(published.name + ".claimed.json").read_text(encoding="utf-8")
    )
    assert marker["claimed_by"] == "agent-A", "the loser overwrote the winner's claim"


def test_force_overrides_and_says_so(published):
    lease(published, minutes=30, owner="agent-A")
    sidecar = claim(published, claimed_by="agent-B", force=True)
    marker = json.loads(sidecar.read_text(encoding="utf-8"))
    assert marker["claimed_by"] == "agent-B"
    assert marker["overrode_lease"] is True


def test_release_is_the_holders_to_do(published):
    lease(published, minutes=30, owner="agent-A")
    with pytest.raises(AlreadyClaimed):
        release(published, owner="agent-B")
    assert release(published, owner="agent-A") is True
    assert lease_of(published) == {}


def test_a_corrupt_sidecar_does_not_deadlock_the_queue(published):
    published.with_name(published.name + LEASE_SUFFIX).write_text("{ not json", encoding="utf-8")
    assert lease_of(published) == {}
    assert claim(published, claimed_by="agent-B").exists()


def test_lease_renewal_by_the_same_owner(published):
    sidecar = lease(published, minutes=10, owner="agent-A")
    until_before = json.loads(sidecar.read_text(encoding="utf-8"))["until"]
    again = lease(published, minutes=60, owner="agent-A")
    until_after = json.loads(again.read_text(encoding="utf-8"))["until"]
    assert until_after > until_before


def test_publish_leaves_no_temp_file_behind(published):
    assert not list(published.parent.glob("*.tmp"))

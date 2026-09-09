"""Rendered bundles must satisfy the normative v0.2 JSON Schema.

The schema lived unvalidated since the renderers moved to bundle_version 0.2:
a drifted field would surface weeks later as an empty pane, never as a test
failure. Every fixture session's bundle is validated; a mutation check keeps
this test honest about actually enforcing the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff import fixtures
from agent_handoff.parsers import all_parsers
from agent_handoff.summarize import summarize

jsonschema = pytest.importorskip("jsonschema")

SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schema" / "handoff-bundle-v0.2.schema.json")
    .read_text(encoding="utf-8")
)


def _bundles(limit_sessions: int = 6) -> list[tuple[str, str, dict]]:
    out = []
    for parser in all_parsers():
        target = fixtures.root_for(parser.cli)
        reaim = getattr(parser, "with_root", None)
        if target is None or reaim is None:
            continue
        scoped = reaim(target)
        codec = getattr(scoped, "codec_ok", None)
        if callable(codec) and not codec():
            continue
        for meta in scoped.list_sessions()[:limit_sessions]:
            raw = scoped.load(meta.session_id)
            if raw is None:
                continue
            out.append((parser.cli, meta.session_id, summarize(raw).to_dict()))
    assert out, "no fixture session produced a bundle"
    return out


def test_all_fixture_bundles_validate():
    for _cli, _sid, bundle in _bundles():
        jsonschema.validate(instance=bundle, schema=SCHEMA)


def test_contract_rejects_drift():
    """The test itself must fail when the contract is broken."""
    import copy

    _, _, bundle = _bundles(limit_sessions=1)[0]
    mutated = dict(bundle, bundle_version="0.1")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=mutated, schema=SCHEMA)
    mutated = copy.deepcopy(bundle)
    del mutated["meta"]["title"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=mutated, schema=SCHEMA)

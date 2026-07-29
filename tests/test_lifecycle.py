"""Lifecycle ops that don't need the embedding stack.

`tests/test_clear_claims.py` covers the same feature but skips without numpy,
so the timezone regression lives here where the base CI job runs it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vouch import audit
from vouch import lifecycle as life
from vouch.proposals import approve, propose_claim
from vouch.storage import KBStore


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    s = KBStore.init(tmp_path)
    s.config_path.write_text(
        "review:\n  approver_role: trusted-agent\n", encoding="utf-8",
    )
    return s


def test_clear_claims_reads_a_naive_before_as_utc(store: KBStore) -> None:
    """A naive `before` filters as UTC instead of aborting the clear.

    `--before 2026-07-01` — the shape the CLI, the console error text, and the
    kb.clear docs all advertise — parses to a naive datetime, while a claim's
    `created_at` is always aware. Comparing the two raised TypeError, which
    surfaced as a traceback on the CLI and a 500 in the review console.
    """
    src = store.put_source(b"the sky is blue on a clear day")
    now = datetime.now(UTC)

    old_pr = propose_claim(
        store, text="old claim", evidence=[src.id], proposed_by="agent"
    )
    old_claim = store.get_claim(approve(store, old_pr.id, approved_by="agent").id)
    old_claim.created_at = now - timedelta(days=2)
    store.update_claim(old_claim)

    new_pr = propose_claim(
        store, text="new claim", evidence=[src.id], proposed_by="agent"
    )
    approve(store, new_pr.id, approved_by="agent")

    naive_cutoff = (now - timedelta(days=1)).replace(tzinfo=None)
    cleared = life.clear_claims(
        store, auto_only=True, before=naive_cutoff, actor="user", dry_run=False
    )

    assert [c.text for c in cleared] == ["old claim"]
    assert store.get_claim(cleared[0].id).status.value == "archived"

    event = next(
        e for e in audit.read_events(store.kb_dir) if e.event == "claim.bulk_clear"
    )
    assert event.data["before"] == naive_cutoff.replace(tzinfo=UTC).isoformat()


def test_clear_claims_aware_before_is_unchanged(store: KBStore) -> None:
    """Normalising the cutoff leaves an already-aware `before` alone."""
    src = store.put_source(b"the sky is blue on a clear day")
    now = datetime.now(UTC)

    pr = propose_claim(store, text="old claim", evidence=[src.id], proposed_by="agent")
    claim = store.get_claim(approve(store, pr.id, approved_by="agent").id)
    claim.created_at = now - timedelta(days=2)
    store.update_claim(claim)

    cutoff = now - timedelta(days=1)
    cleared = life.clear_claims(
        store, auto_only=True, before=cutoff, actor="user", dry_run=True
    )

    assert [c.text for c in cleared] == ["old claim"]

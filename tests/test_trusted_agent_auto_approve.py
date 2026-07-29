"""Trusted-agent auto-approval: the full drain behind auto-approval-by-default.

With ``review.approver_role: trusted-agent`` (the starter-config default),
``auto_approve_pending`` approves every pending proposal through the normal
``approve()`` path — claims, pages, entities, relations. What stays pending is
the human-call residue: protected page kinds, DELETE proposals, and id
conflicts. Without trusted-agent the drain degrades to the receipt gate, and
with no gate open it is a no-op — the review gate is never silently bypassed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vouch.models import ProposalStatus
from vouch.proposals import (
    auto_approve_pending,
    propose_claim,
    propose_delete,
    propose_page,
    propose_quoted_claim,
    propose_relation,
)
from vouch.storage import KBStore


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    return KBStore.init(tmp_path)


def _set_review(store: KBStore, review_yaml: str) -> None:
    store.config_path.write_text(review_yaml, encoding="utf-8")


def test_starter_config_defaults_to_trusted_agent(store: KBStore) -> None:
    # a fresh kb ships with auto approval on: no config edit, no human step.
    import yaml

    loaded = yaml.safe_load(store.config_path.read_text(encoding="utf-8"))
    assert loaded["review"]["approver_role"] == "trusted-agent"
    assert loaded["review"]["auto_approve_on_receipt"] is True


def test_trusted_agent_drains_all_kinds(store: KBStore) -> None:
    src = store.put_source(b"alpha beta gamma")
    receipted = propose_quoted_claim(
        store, text="mentions beta", source_id=src.id, quote="beta",
        proposed_by="agent-a",
    )
    assert receipted is not None
    bare = propose_claim(
        store, text="bare assertion", evidence=[src.id], proposed_by="agent-a",
    )
    page = propose_page(
        store, title="session notes", body="what happened",
        source_ids=[src.id], proposed_by="agent-a", page_type="session",
    )

    approved = auto_approve_pending(store)

    # trusted-agent clears everything: the unreceipted claim and the page
    # too, not just the receipt-verified claim.
    assert len(approved) == 3
    assert store.get_proposal(receipted.id).status is ProposalStatus.APPROVED
    assert store.get_proposal(bare.id).status is ProposalStatus.APPROVED
    assert store.get_proposal(page.id).status is ProposalStatus.APPROVED


def test_trusted_agent_drains_relations(store: KBStore) -> None:
    src = store.put_source(b"alpha beta gamma")
    a = propose_claim(store, text="claim a", evidence=[src.id], proposed_by="x")
    b = propose_claim(store, text="claim b", evidence=[src.id], proposed_by="x")
    assert len(auto_approve_pending(store)) == 2
    rel = propose_relation(
        store, src=str(a.proposal.payload["id"]), relation="supports",
        target=str(b.proposal.payload["id"]), proposed_by="x",
    )
    approved = auto_approve_pending(store)
    assert len(approved) == 1
    assert store.get_proposal(rel.id).status is ProposalStatus.APPROVED


def test_protected_page_kind_stays_pending(store: KBStore) -> None:
    _set_review(
        store,
        "review:\n  approver_role: trusted-agent\n"
        "page_kinds:\n  decision:\n    protected: true\n",
    )
    page = propose_page(
        store, title="a decision", body="we decided", proposed_by="agent-a",
        page_type="decision",
    )
    assert auto_approve_pending(store) == []
    assert store.get_proposal(page.id).status is ProposalStatus.PENDING


def test_delete_proposals_never_drained(store: KBStore) -> None:
    src = store.put_source(b"alpha beta gamma")
    filed = propose_claim(
        store, text="to be deleted", evidence=[src.id], proposed_by="x",
    )
    assert len(auto_approve_pending(store)) == 1
    deletion = propose_delete(
        store, target_kind="claim", target_id=str(filed.proposal.payload["id"]),
        proposed_by="x",
    )
    assert auto_approve_pending(store) == []
    assert store.get_proposal(deletion.id).status is ProposalStatus.PENDING


def test_duplicate_claim_rejected_not_repiled(store: KBStore) -> None:
    src = store.put_source(b"alpha beta gamma")
    propose_quoted_claim(
        store, text="mentions beta", source_id=src.id, quote="beta",
        proposed_by="agent-a",
    )
    assert len(auto_approve_pending(store)) == 1
    again = propose_quoted_claim(
        store, text="mentions beta", source_id=src.id, quote="beta",
        proposed_by="agent-a",
    )
    assert again is not None
    assert auto_approve_pending(store) == []
    decided = store.get_proposal(again.id)
    assert decided.status is ProposalStatus.REJECTED
    assert "duplicate" in (decided.decision_reason or "")


def test_falls_back_to_receipt_drain_without_trusted_agent(store: KBStore) -> None:
    _set_review(store, "review:\n  auto_approve_on_receipt: true\n")
    src = store.put_source(b"alpha beta gamma")
    good = propose_quoted_claim(
        store, text="mentions beta", source_id=src.id, quote="beta",
        proposed_by="agent-a",
    )
    assert good is not None
    bare = propose_claim(
        store, text="bare assertion", evidence=[src.id], proposed_by="agent-a",
    )
    page = propose_page(
        store, title="session notes", body="what happened",
        source_ids=[src.id], proposed_by="agent-a", page_type="session",
    )
    approved = auto_approve_pending(store)
    # receipt gate only: the verified claim drains, everything else pends.
    assert len(approved) == 1
    assert store.get_proposal(good.id).status is ProposalStatus.APPROVED
    assert store.get_proposal(bare.id).status is ProposalStatus.PENDING
    assert store.get_proposal(page.id).status is ProposalStatus.PENDING


def test_noop_when_no_gate_open(store: KBStore) -> None:
    _set_review(store, "review:\n  auto_approve_on_receipt: false\n")
    src = store.put_source(b"alpha beta gamma")
    propose_quoted_claim(
        store, text="mentions beta", source_id=src.id, quote="beta",
        proposed_by="agent-a",
    )
    propose_page(
        store, title="session notes", body="what happened",
        source_ids=[src.id], proposed_by="agent-a", page_type="session",
    )
    assert auto_approve_pending(store) == []

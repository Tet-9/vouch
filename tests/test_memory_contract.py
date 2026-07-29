"""The five-tool memory contract: gate-respecting saves, subject-scoped search."""

from __future__ import annotations

from pathlib import Path

import pytest

from vouch.memory_contract import CONTRACT_TOOLS, MemoryContract, MemoryHit
from vouch.storage import ArtifactNotFoundError, KBStore


def _kb(tmp_path: Path, *, receipt_gate: bool = True) -> KBStore:
    # init's starter config already opts into the receipt gate (phase d);
    # the gate-off arm must configure it off explicitly.
    store = KBStore.init(tmp_path / "kb")
    flag = "true" if receipt_gate else "false"
    store.config_path.write_text(
        f"review:\n  auto_approve_on_receipt: {flag}\n", encoding="utf-8"
    )
    return store


def test_contract_names_the_five_ditto_tools() -> None:
    assert CONTRACT_TOOLS == (
        "save_memory",
        "search_memories",
        "search_subjects",
        "fetch_by_id",
        "search_in_subject",
    )


def test_save_then_search_roundtrip(tmp_path: Path) -> None:
    contract = MemoryContract(_kb(tmp_path))
    saved = contract.save_memory(
        "for the record, my favorite editor is zorvex right now."
    )
    assert saved, "receipt-gated save produced no durable memory"
    hits = contract.search_memories("favorite editor")
    assert any("zorvex" in h.text for h in hits)


def test_save_without_receipt_gate_stays_pending(tmp_path: Path) -> None:
    # The review gate is never silently bypassed: with auto-approve off the
    # save files a proposal and nothing becomes durable or searchable.
    contract = MemoryContract(_kb(tmp_path, receipt_gate=False))
    saved = contract.save_memory("the staging region is vora-3 as of today.")
    assert saved == []
    assert contract.search_memories("staging region") == []


def test_fetch_by_id_returns_saved_memory(tmp_path: Path) -> None:
    contract = MemoryContract(_kb(tmp_path))
    saved = contract.save_memory("the project codename is mulopi now.")
    hit = contract.fetch_by_id(saved[0])
    assert isinstance(hit, MemoryHit)
    assert hit.id == saved[0]
    assert "mulopi" in hit.text
    assert hit.receipt_backed is True


def test_fetch_by_id_unknown_raises(tmp_path: Path) -> None:
    contract = MemoryContract(_kb(tmp_path))
    with pytest.raises(ArtifactNotFoundError):
        contract.fetch_by_id("no-such-memory")


def test_search_subjects_matches_saved_subjects(tmp_path: Path) -> None:
    contract = MemoryContract(_kb(tmp_path))
    contract.save_memory("my usual coffee order is a flat white.", subject="preferences")
    contract.save_memory("the deploy day moved to tuesday.", subject="ops-runbook")
    assert contract.search_subjects("prefer") == ["preferences"]
    assert contract.search_subjects("runbook") == ["ops-runbook"]
    assert contract.search_subjects("r") == ["ops-runbook", "preferences"]


def test_search_in_subject_scopes_hits(tmp_path: Path) -> None:
    contract = MemoryContract(_kb(tmp_path))
    contract.save_memory(
        "the api rate limit is 640 requests per minute.", subject="ops-runbook"
    )
    contract.save_memory(
        "personal note: my api rate limit worry is overblown.", subject="journal"
    )
    hits = contract.search_in_subject("ops-runbook", "api rate limit")
    assert hits, "subject-scoped search found nothing"
    assert all(h.subject == "ops-runbook" for h in hits)
    assert any("640" in h.text for h in hits)

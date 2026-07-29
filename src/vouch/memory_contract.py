"""The five-tool memory contract, implemented over a vouch KB.

Ditto's mining contract (SN118) scores a harness on exactly five tools:
save a memory, search memories, search subjects, fetch by id, and search
within a subject. This module is vouch's side of that shared contract — a
thin adapter over the real store, so a head-to-head can run both engines
on one task set instead of comparing incomparable benchmark numbers.

Two properties are non-negotiable and differ from a plain memory store:

* **Saves go through the review gate.** ``save_memory`` runs the same
  receipt-gated capture loop production uses (``extract.ingest_source``).
  With ``review.auto_approve_on_receipt`` off, a save files a proposal and
  returns nothing durable — the gate is never silently bypassed, even
  inside a benchmark harness.
* **Subjects are provenance, not labels.** A memory's subject is the title
  of the source it cites; there is no free-floating subject field to
  drift from the evidence. Subject search and subject-scoped search both
  resolve through citations.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

from .context import search_kb
from .extract import ingest_source
from .models import Claim, ClaimStatus, Evidence
from .receipts import verify_receipt
from .storage import ArtifactNotFoundError, KBStore

CONTRACT_TOOLS = (
    "save_memory",
    "search_memories",
    "search_subjects",
    "fetch_by_id",
    "search_in_subject",
)

# Mirrors the retracted set the context pack excludes: a superseded,
# archived, or redacted claim is not a live memory.
_RETRACTED = frozenset(
    (ClaimStatus.SUPERSEDED, ClaimStatus.ARCHIVED, ClaimStatus.REDACTED)
)


@dataclass(frozen=True)
class MemoryHit:
    """One memory as the contract returns it."""

    id: str
    text: str
    score: float
    subject: str | None
    receipt_backed: bool


class MemoryContract:
    """The five contract tools over one vouch KB."""

    def __init__(self, store: KBStore, *, actor: str = "memory-contract") -> None:
        self.store = store
        self.actor = actor

    def save_memory(self, text: str, *, subject: str | None = None) -> list[str]:
        """Store one memory; return the ids that became durable.

        An empty list means the receipt gate is off and the memory is
        pending human review — filed, not durable.
        """
        _, approved = ingest_source(
            self.store, text.encode("utf-8"),
            proposed_by=self.actor, title=subject,
        )
        return [claim.id for claim in approved]

    def search_memories(self, query: str, *, limit: int = 10) -> list[MemoryHit]:
        result = search_kb(self.store, query=query, limit=limit)
        hits: list[MemoryHit] = []
        for row in result["hits"]:
            if row["kind"] != "claim":
                continue
            try:
                claim = self.store.get_claim(str(row["id"]))
            except ArtifactNotFoundError:
                continue
            if claim.status in _RETRACTED:
                continue
            hits.append(self._hit(claim, score=float(row["score"])))
        return hits

    def search_subjects(self, query: str, *, limit: int = 10) -> list[str]:
        needle = query.lower()
        subjects = {
            subject
            for claim in self.store.list_claims()
            if claim.status not in _RETRACTED
            and (subject := self._subject_of(claim)) is not None
            and needle in subject.lower()
        }
        return sorted(subjects)[:limit]

    def fetch_by_id(self, memory_id: str) -> MemoryHit:
        return self._hit(self.store.get_claim(memory_id), score=1.0)

    def search_in_subject(
        self, subject: str, query: str, *, limit: int = 10
    ) -> list[MemoryHit]:
        wide = self.search_memories(query, limit=max(limit * 5, 25))
        return [hit for hit in wide if hit.subject == subject][:limit]

    def _hit(self, claim: Claim, *, score: float) -> MemoryHit:
        return MemoryHit(
            id=claim.id,
            text=claim.text,
            score=score,
            subject=self._subject_of(claim),
            receipt_backed=any(
                verify_receipt(
                    ev, self.store.read_source_content(ev.source_id)
                ).verified
                for ev in self._evidence_of(claim)
            ),
        )

    def _evidence_of(self, claim: Claim) -> list[Evidence]:
        out: list[Evidence] = []
        for cid in claim.evidence:
            try:
                out.append(self.store.get_evidence(cid))
            except ArtifactNotFoundError:
                continue  # a bare source-id citation carries no receipt
        return out

    def _subject_of(self, claim: Claim) -> str | None:
        for cid in claim.evidence:
            source_id = cid
            with suppress(ArtifactNotFoundError):
                source_id = self.store.get_evidence(cid).source_id
            try:
                title = self.store.get_source(source_id).title
            except ArtifactNotFoundError:
                continue
            if title:
                return title
        return None

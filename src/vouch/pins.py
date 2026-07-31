"""Explicit pins — a working set that always enters the context pack (issue #615).

When deep in one piece of work there are a handful of artifacts that should
be in front of the agent on every turn — the spec page, the decision that
constrains the design, the claim that says why the obvious approach was
already rejected. Whether they survive salience-based ranking today depends
entirely on the query; a ranker optimizing for relevance drops them the
moment the conversation moves on.

Deliberately separate from memory (mirrors ditto's bookmarks vs. memory
split, heyditto.ai/docs/bookmarks): pins are manual, never auto-created, and
do not feed salience/hot_memory. A pin is a pointer to an already-approved
artifact, not a new claim -- nothing durable is asserted, so there is no
review gate here.

Storage: pins.json (committed, team-shared) and pins.local.json (gitignored,
--local personal pins), merged at read time with committed pins winning on
id collision. Both are small JSON lists, not a KBStore artifact kind -- no
schema change, no four-site registration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .storage import ArtifactNotFoundError, KBStore

# NOTE: _page_is_live and _RETRACTED_CLAIM_STATUSES are imported lazily
# inside _resolve_kind(), not at module level -- context.py imports this
# module too (to prepend pinned hits), so a top-level import here would be
# circular. Both live in context.py deliberately (its own docstring: "kept
# in three places is what let kb.context keep serving archived pages after
# #581 fixed kb.search") -- reusing them, even lazily, is still correct
# over reimplementing the check a third time.

logger = logging.getLogger(__name__)

FILENAME = "pins.json"
LOCAL_FILENAME = "pins.local.json"
DEFAULT_BUDGET_SHARE = 0.2


class PinError(Exception):
    """Raised for invalid pin operations (unknown/archived artifact, duplicate pin)."""


@dataclass(frozen=True)
class PinsConfig:
    budget_share: float = DEFAULT_BUDGET_SHARE


def load_pins_config(store: KBStore) -> PinsConfig:
    """Read ``retrieval.pins`` from config.yaml; fall back to defaults."""
    try:
        loaded = yaml.safe_load(store.config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return PinsConfig()
    if not isinstance(loaded, dict):
        return PinsConfig()
    retrieval = loaded.get("retrieval")
    raw = retrieval.get("pins") if isinstance(retrieval, dict) else None
    if not isinstance(raw, dict):
        return PinsConfig()
    try:
        budget_share = float(raw.get("budget_share", DEFAULT_BUDGET_SHARE))
    except (TypeError, ValueError):
        budget_share = DEFAULT_BUDGET_SHARE
    if not (0.0 <= budget_share <= 1.0):
        budget_share = DEFAULT_BUDGET_SHARE
    return PinsConfig(budget_share=budget_share)


@dataclass(frozen=True)
class PinnedArtifact:
    id: str
    kind: str  # "claim" | "page"
    pinned_at: str  # ISO-8601 UTC timestamp
    pinned_by: str
    expires_at: str | None = None  # ISO-8601 UTC timestamp, or None (never)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        now = now or datetime.now(UTC)
        try:
            exp = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return False
        return now >= exp

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "pinned_at": self.pinned_at,
            "pinned_by": self.pinned_by,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PinnedArtifact:
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            pinned_at=str(data["pinned_at"]),
            pinned_by=str(data.get("pinned_by", "")),
            expires_at=data.get("expires_at"),
        )


def _pins_path(store: KBStore, *, local: bool) -> Path:
    return store.kb_dir / (LOCAL_FILENAME if local else FILENAME)


def _ensure_local_ignored(store: KBStore) -> None:
    """Append pins.local.json to .vouch/.gitignore when a pre-existing KB lacks it.

    Mirrors retrieval_events.py's _ensure_ignored: new KBs won't get this
    pattern until the init template is updated, so pre-existing KBs need a
    first-write backfill. Best-effort -- an unwritable .gitignore must not
    break pinning.
    """
    gi = store.kb_dir / ".gitignore"
    try:
        text = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if LOCAL_FILENAME in text:
            return
        if text and not text.endswith("\n"):
            text += "\n"
        gi.write_text(text + LOCAL_FILENAME + "\n", encoding="utf-8")
    except OSError:
        return


def _read_pins(store: KBStore, *, local: bool) -> list[PinnedArtifact]:
    path = _pins_path(store, local=local)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[PinnedArtifact] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(PinnedArtifact.from_dict(entry))
        except (KeyError, ValueError):
            continue
    return out


def _write_pins(store: KBStore, pins: list[PinnedArtifact], *, local: bool) -> None:
    path = _pins_path(store, local=local)
    path.write_text(
        json.dumps([p.to_dict() for p in pins], indent=2) + "\n", encoding="utf-8"
    )
    if local:
        _ensure_local_ignored(store)


def _resolve_kind(store: KBStore, artifact_id: str) -> str | None:
    """'claim' or 'page' if a live (non-retracted, non-archived) artifact
    exists with this id, else None. A pin to a dead artifact would silently
    inject nothing into the pack, so pinning rejects it up front instead."""
    from .context import _RETRACTED_CLAIM_STATUSES, _page_is_live

    try:
        claim = store.get_claim(artifact_id)
    except ArtifactNotFoundError:
        claim = None
    if claim is not None:
        # Same retracted-status check build_context_pack applies to search hits.
        if claim.status in _RETRACTED_CLAIM_STATUSES:
            return None
        return "claim"
    if _page_is_live(store, artifact_id):
        return "page"
    return None


def pin(
    store: KBStore,
    artifact_id: str,
    *,
    pinned_by: str,
    local: bool = False,
    expires_in_days: float | None = None,
) -> PinnedArtifact:
    """Pin a claim or page so it always enters the context pack.

    Raises PinError if the artifact doesn't exist (or is retracted/archived),
    or is already pinned (in either the committed or local file).
    """
    kind = _resolve_kind(store, artifact_id)
    if kind is None:
        raise PinError(f"no live claim or page with id {artifact_id!r}")

    if any(p.id == artifact_id for p in list_pins(store, include_expired=True)):
        raise PinError(f"{artifact_id!r} is already pinned")

    expires_at = None
    if expires_in_days is not None:
        expires_at = (datetime.now(UTC) + timedelta(days=expires_in_days)).isoformat()

    existing = _read_pins(store, local=local)
    new_pin = PinnedArtifact(
        id=artifact_id,
        kind=kind,
        pinned_at=datetime.now(UTC).isoformat(),
        pinned_by=pinned_by,
        expires_at=expires_at,
    )
    existing.append(new_pin)
    _write_pins(store, existing, local=local)
    return new_pin


def unpin(store: KBStore, artifact_id: str) -> bool:
    """Remove a pin, checking both committed and local files. Returns True if found."""
    removed = False
    for local in (False, True):
        pins = _read_pins(store, local=local)
        filtered = [p for p in pins if p.id != artifact_id]
        if len(filtered) != len(pins):
            _write_pins(store, filtered, local=local)
            removed = True
    return removed


def list_pins(store: KBStore, *, include_expired: bool = False) -> list[PinnedArtifact]:
    """All active pins, committed + local merged, deduplicated (committed wins
    on id collision -- a personal local pin never shadows a team decision)."""
    committed = _read_pins(store, local=False)
    local = _read_pins(store, local=True)
    seen_ids = {p.id for p in committed}
    combined = committed + [p for p in local if p.id not in seen_ids]
    if not include_expired:
        combined = [p for p in combined if not p.is_expired()]
    return combined

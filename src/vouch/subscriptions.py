"""Read-only KB subscriptions -- federate search without copying (issue #610).

`vouch hub` export/import (#536) moves artifacts through the receiving gate
and they become local, forked copies -- correct for "make this mine", wrong
for "let me read yours" (duplicates, drifts independently, forces re-review
on every upstream edit). Subscription is the safer, ditto-style primitive
(heyditto.ai/docs/knowledge-graph-sharing): a subscribed KB's approved
knowledge joins local search/context results, live, read-only, never
copied, never locally proposable/approvable.

Read-only is mostly free by construction, not a separate enforced gate: a
federated hit's id is namespaced "<kb_id>:<artifact_id>" and never resolves
against the local store, so store.get_claim()/propose()/approve() on a
federated id simply finds nothing local to act on. Wanting to *own* a
federated fact means importing it through the existing gated hub path,
unchanged.

One hop only: a subscribed KB's own subscriptions.json is never read (this
module never recurses into a foreign KB's subscriptions).

Storage: subscriptions.json, a small committed list (mirrors the hub
registry's shape, but per-KB rather than per-machine) -- additive, no
schema change to stored artifacts. The origin/trust tag lives on the
*result*, never the artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import hub
from .storage import KBStore

logger = logging.getLogger(__name__)

FILENAME = "subscriptions.json"
TRUST_LEVELS = ("unverified", "trusted")
DEFAULT_TRUST_LEVEL = "unverified"
DEFAULT_BUDGET_SHARE = 0.3


class SubscriptionError(Exception):
    """Raised for invalid subscription operations (unresolvable ref, self-
    subscribe, duplicate subscription)."""


@dataclass(frozen=True)
class Subscription:
    kb_id: str
    path: str
    name: str
    trust_level: str
    subscribed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kb_id": self.kb_id,
            "path": self.path,
            "name": self.name,
            "trust_level": self.trust_level,
            "subscribed_at": self.subscribed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Subscription:
        return cls(
            kb_id=str(data["kb_id"]),
            path=str(data["path"]),
            name=str(data.get("name") or data["kb_id"]),
            trust_level=str(data.get("trust_level") or DEFAULT_TRUST_LEVEL),
            subscribed_at=str(data.get("subscribed_at", "")),
        )


@dataclass(frozen=True)
class SubscriptionsConfig:
    budget_share: float = DEFAULT_BUDGET_SHARE


def load_subscriptions_config(store: KBStore) -> SubscriptionsConfig:
    """Read ``retrieval.subscriptions`` from config.yaml; fall back to defaults."""
    try:
        loaded = yaml.safe_load(store.config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return SubscriptionsConfig()
    if not isinstance(loaded, dict):
        return SubscriptionsConfig()
    retrieval = loaded.get("retrieval")
    raw = retrieval.get("subscriptions") if isinstance(retrieval, dict) else None
    if not isinstance(raw, dict):
        return SubscriptionsConfig()
    try:
        budget_share = float(raw.get("budget_share", DEFAULT_BUDGET_SHARE))
    except (TypeError, ValueError):
        budget_share = DEFAULT_BUDGET_SHARE
    if not (0.0 <= budget_share <= 1.0):
        budget_share = DEFAULT_BUDGET_SHARE
    return SubscriptionsConfig(budget_share=budget_share)


def _subscriptions_path(store: KBStore) -> Path:
    return store.kb_dir / FILENAME


def _read_subscriptions(store: KBStore) -> list[Subscription]:
    path = _subscriptions_path(store)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[Subscription] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(Subscription.from_dict(entry))
        except (KeyError, ValueError):
            continue
    return out


def _write_subscriptions(store: KBStore, subs: list[Subscription]) -> None:
    path = _subscriptions_path(store)
    path.write_text(
        json.dumps([s.to_dict() for s in subs], indent=2) + "\n", encoding="utf-8"
    )


def _resolve_ref(ref: str) -> tuple[str, Path] | None:
    """A registered kb_id (vouch hub registry), or a filesystem path, to
    (kb_id, root). None if neither resolves to a KB that exists on disk."""
    for entry in hub.load_registry():
        if entry.kb_id == ref:
            root = Path(entry.path)
            return (entry.kb_id, root) if (root / ".vouch").is_dir() else None
    root = Path(ref).expanduser().resolve()
    if not (root / ".vouch").is_dir():
        return None
    identity = KBStore(root).identity()
    if identity is None:
        return None
    kb_id, _name = identity
    return kb_id, root


def subscribe(
    store: KBStore, kb_ref: str, *, trust_level: str = DEFAULT_TRUST_LEVEL
) -> Subscription:
    """Subscribe to another KB's approved knowledge, read-only.

    kb_ref is a registered kb_id (vouch hub registry) or a filesystem path.
    Raises SubscriptionError if it doesn't resolve to an existing KB, is
    this KB's own identity, or is already subscribed.
    """
    if trust_level not in TRUST_LEVELS:
        raise SubscriptionError(
            f"unknown trust level {trust_level!r} (use {'/'.join(TRUST_LEVELS)})"
        )
    resolved = _resolve_ref(kb_ref)
    if resolved is None:
        raise SubscriptionError(f"no KB found at {kb_ref!r}")
    kb_id, root = resolved

    own_identity = store.identity()
    if own_identity is not None and own_identity[0] == kb_id:
        raise SubscriptionError("cannot subscribe to this KB's own identity")

    existing = _read_subscriptions(store)
    if any(s.kb_id == kb_id for s in existing):
        raise SubscriptionError(f"already subscribed to {kb_id!r}")

    foreign_identity = KBStore(root).identity()
    name = foreign_identity[1] if foreign_identity else root.name

    sub = Subscription(
        kb_id=kb_id,
        path=str(root),
        name=name,
        trust_level=trust_level,
        subscribed_at=datetime.now(UTC).isoformat(),
    )
    existing.append(sub)
    _write_subscriptions(store, existing)
    return sub


def unsubscribe(store: KBStore, kb_ref: str) -> bool:
    """Remove a subscription by kb_id or path. Returns True if found."""
    existing = _read_subscriptions(store)
    filtered = [s for s in existing if s.kb_id != kb_ref and s.path != kb_ref]
    if len(filtered) == len(existing):
        return False
    _write_subscriptions(store, filtered)
    return True


def list_subscriptions(store: KBStore) -> list[Subscription]:
    return _read_subscriptions(store)


def open_subscribed_store(sub: Subscription) -> KBStore | None:
    """Open a subscribed KB read-only, or None if it's no longer there
    (moved/deleted since subscribing) -- a dead subscription degrades to
    silently contributing nothing, not an error."""
    root = Path(sub.path)
    if not (root / ".vouch").is_dir():
        return None
    return KBStore(root)

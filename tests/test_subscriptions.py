"""Read-only KB subscriptions (#610) — federate search/context without copying."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from vouch import health, hub, subscriptions
from vouch.context import build_context_pack, search_kb
from vouch.models import Claim
from vouch.storage import KBStore


@pytest.fixture(autouse=True)
def _isolated_machine(tmp_path_factory, monkeypatch):
    """Fake $HOME so subscribe's registry lookup never touches the real machine."""
    fake_home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv(hub.REGISTRY_ENV, str(fake_home / "registry.yaml"))
    monkeypatch.delenv("VOUCH_KB_PATH", raising=False)
    monkeypatch.delenv("VOUCH_PROJECT_DIR", raising=False)
    return fake_home


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    return KBStore.init(tmp_path / "local")


def _kb_with_claim(root: Path, *, claim_id: str, text: str) -> KBStore:
    kb = KBStore.init(root)
    src = kb.put_source(text.encode(), title="doc")
    kb.put_claim(Claim(id=claim_id, text=text, evidence=[src.id]))
    health.rebuild_index(kb)
    return kb


# --- subscribe / unsubscribe / list ----------------------------------------


def test_subscribe_by_path(store: KBStore, tmp_path: Path) -> None:
    foreign = _kb_with_claim(tmp_path / "foreign", claim_id="f1", text="foreign fact")
    sub = subscriptions.subscribe(store, str(tmp_path / "foreign"))
    assert sub.kb_id == foreign.identity()[0]
    assert sub.trust_level == "unverified"
    listed = subscriptions.list_subscriptions(store)
    assert [s.kb_id for s in listed] == [sub.kb_id]


def test_subscribe_rejects_own_identity(store: KBStore) -> None:
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.subscribe(store, str(store.kb_dir.parent))


def test_subscribe_rejects_duplicate(store: KBStore, tmp_path: Path) -> None:
    _kb_with_claim(tmp_path / "foreign", claim_id="f1", text="foreign fact")
    subscriptions.subscribe(store, str(tmp_path / "foreign"))
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.subscribe(store, str(tmp_path / "foreign"))


def test_subscribe_rejects_nonexistent_kb(store: KBStore, tmp_path: Path) -> None:
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.subscribe(store, str(tmp_path / "nowhere"))


def test_subscribe_rejects_unknown_trust_level(store: KBStore, tmp_path: Path) -> None:
    _kb_with_claim(tmp_path / "foreign", claim_id="f1", text="foreign fact")
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.subscribe(store, str(tmp_path / "foreign"), trust_level="bogus")


def test_unsubscribe_removes_entry(store: KBStore, tmp_path: Path) -> None:
    foreign = _kb_with_claim(tmp_path / "foreign", claim_id="f1", text="foreign fact")
    subscriptions.subscribe(store, str(tmp_path / "foreign"))
    assert subscriptions.unsubscribe(store, foreign.identity()[0]) is True
    assert subscriptions.list_subscriptions(store) == []


def test_unsubscribe_missing_returns_false(store: KBStore) -> None:
    assert subscriptions.unsubscribe(store, "nope") is False


def test_open_subscribed_store_returns_none_when_moved(
    store: KBStore, tmp_path: Path,
) -> None:
    foreign_root = tmp_path / "foreign"
    _kb_with_claim(foreign_root, claim_id="f1", text="foreign fact")
    sub = subscriptions.subscribe(store, str(foreign_root))
    shutil.rmtree(foreign_root)
    assert subscriptions.open_subscribed_store(sub) is None


# --- federation: search -----------------------------------------------------


def test_search_kb_includes_federated_hit_when_local_has_slack(
    store: KBStore, tmp_path: Path,
) -> None:
    foreign = _kb_with_claim(
        tmp_path / "foreign", claim_id="f1", text="rust ownership rules",
    )
    subscriptions.subscribe(store, str(tmp_path / "foreign"))
    health.rebuild_index(store)
    result = search_kb(store, query="rust ownership", limit=10)
    federated = [h for h in result["hits"] if h.get("federated")]
    assert len(federated) == 1
    assert federated[0]["origin_kb_id"] == foreign.identity()[0]
    assert federated[0]["trust_level"] == "unverified"
    assert federated[0]["id"] == f"{foreign.identity()[0]}:f1"


def test_search_kb_federated_hits_never_displace_local(
    store: KBStore, tmp_path: Path,
) -> None:
    for i in range(10):
        src = store.put_source(f"e{i}".encode())
        store.put_claim(
            Claim(id=f"local{i}", text=f"local claim about widgets {i}", evidence=[src.id]),
        )
    health.rebuild_index(store)
    _kb_with_claim(tmp_path / "foreign", claim_id="f1", text="widgets foreign fact")
    subscriptions.subscribe(store, str(tmp_path / "foreign"))
    result = search_kb(store, query="widgets", limit=10)
    assert len(result["hits"]) == 10  # local already fills the whole limit
    assert not any(h.get("federated") for h in result["hits"])


def test_search_kb_federation_is_one_hop(store: KBStore, tmp_path: Path) -> None:
    # store -> subscribes to B -> subscribes to C. Searching store must not
    # surface C's data.
    _kb_with_claim(tmp_path / "c", claim_id="c1", text="deep transitive fact")
    kb_b = KBStore.init(tmp_path / "b")
    subscriptions.subscribe(kb_b, str(tmp_path / "c"))
    subscriptions.subscribe(store, str(tmp_path / "b"))
    health.rebuild_index(store)
    result = search_kb(store, query="deep transitive", limit=10)
    assert result["hits"] == []


def test_search_kb_respects_budget_share(store: KBStore, tmp_path: Path) -> None:
    # Empty local KB -> all 10 slots are slack; budget_share caps how many
    # federation may actually take.
    cfg = yaml.safe_load(store.config_path.read_text(encoding="utf-8"))
    cfg.setdefault("retrieval", {})["subscriptions"] = {"budget_share": 0.2}
    store.config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    foreign = KBStore.init(tmp_path / "foreign")
    for i in range(10):
        src = foreign.put_source(f"e{i}".encode())
        foreign.put_claim(
            Claim(id=f"f{i}", text=f"gadget fact number {i}", evidence=[src.id]),
        )
    health.rebuild_index(foreign)
    subscriptions.subscribe(store, str(tmp_path / "foreign"))
    health.rebuild_index(store)

    result = search_kb(store, query="gadget", limit=10)
    federated = [h for h in result["hits"] if h.get("federated")]
    assert len(federated) == 2  # round(10 * 0.2)


def test_dead_subscription_contributes_nothing(store: KBStore, tmp_path: Path) -> None:
    foreign_root = tmp_path / "foreign"
    _kb_with_claim(foreign_root, claim_id="f1", text="soon to vanish fact")
    subscriptions.subscribe(store, str(foreign_root))
    shutil.rmtree(foreign_root)
    health.rebuild_index(store)
    result = search_kb(store, query="vanish", limit=10)
    assert result["hits"] == []


# --- federation: context pack -----------------------------------------------


def test_build_context_pack_tags_federated_item_origin_and_trust(
    store: KBStore, tmp_path: Path,
) -> None:
    foreign = _kb_with_claim(
        tmp_path / "foreign", claim_id="f1", text="graph databases model relations",
    )
    subscriptions.subscribe(store, str(tmp_path / "foreign"), trust_level="trusted")
    health.rebuild_index(store)
    pack = build_context_pack(store, query="graph databases", limit=10)
    items = pack["items"] if isinstance(pack, dict) else pack.items
    fed = [
        i for i in items
        if (i.get("origin") if isinstance(i, dict) else i.origin) == foreign.identity()[0]
    ]
    assert len(fed) == 1
    fed_item = fed[0]
    trust = fed_item.get("trust_level") if isinstance(fed_item, dict) else fed_item.trust_level
    assert trust == "trusted"

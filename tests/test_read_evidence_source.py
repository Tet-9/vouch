"""kb.read_evidence / kb.read_source — by-id reads for citation targets.

Added so UI surfaces (the console's provenance tree, citation lists) can
open the artifacts a claim cites, not just the claim itself. Method-list
parity across MCP/JSONL/CLI is covered by test_capabilities; this file
tests the behaviour of the JSONL handlers and the CLI mirrors.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from vouch.cli import cli
from vouch.jsonl_server import handle_request
from vouch.models import Claim, Evidence
from vouch.storage import KBStore


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    s = KBStore.init(tmp_path)
    src = s.put_source(b"the retry limit is 3", title="ops-runbook")
    s.put_evidence(
        Evidence(
            id="ev-runbook-retry",
            source_id=src.id,
            locator="L1",
            quote="the retry limit is 3",
        )
    )
    s.put_claim(Claim(id="c1", text="retry limit is 3", evidence=["ev-runbook-retry"]))
    return s


def _rpc(method: str, params: dict) -> dict:
    resp = handle_request({"id": "t", "method": method, "params": params})
    assert resp["ok"], resp
    return resp["result"]  # type: ignore[no-any-return]


def test_jsonl_read_evidence(store: KBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(store.root)
    result = _rpc("kb.read_evidence", {"evidence_id": "ev-runbook-retry"})
    assert result["id"] == "ev-runbook-retry"
    assert result["quote"] == "the retry limit is 3"
    assert result["source_id"]


def test_jsonl_read_source(store: KBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(store.root)
    ev = _rpc("kb.read_evidence", {"evidence_id": "ev-runbook-retry"})
    result = _rpc("kb.read_source", {"source_id": ev["source_id"]})
    assert result["id"] == ev["source_id"]
    assert result["title"] == "ops-runbook"
    # metadata only — the raw content is not in the response
    assert "content" not in result


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("kb.read_evidence", {"evidence_id": "ev-nope"}),
        ("kb.read_source", {"source_id": "0" * 64}),
    ],
)
def test_jsonl_read_missing_is_an_error(
    store: KBStore, monkeypatch: pytest.MonkeyPatch, method: str, params: dict
) -> None:
    monkeypatch.chdir(store.root)
    resp = handle_request({"id": "t", "method": method, "params": params})
    assert not resp["ok"]


def test_cli_read_evidence_and_source(
    store: KBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(store.root)
    runner = CliRunner()
    out = runner.invoke(cli, ["read-evidence", "ev-runbook-retry"])
    assert out.exit_code == 0, out.output
    assert "the retry limit is 3" in out.output

    src_id = store.get_evidence("ev-runbook-retry").source_id
    out = runner.invoke(cli, ["read-source", src_id])
    assert out.exit_code == 0, out.output
    assert "ops-runbook" in out.output

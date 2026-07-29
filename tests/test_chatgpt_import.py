"""`vouch import-chatgpt` — ChatGPT export parsing + review-gated import.

ChatGPT's data export stores each conversation as a branching mapping
tree. The parser walks the canonical branch and pairs each user turn with
the assistant turn that answered it; the import path files one PENDING,
source-cited session page per conversation, deduped on the conversation
id. Fixtures use placeholder data only (alice-example / acme-example).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from vouch import chatgpt_import as ci
from vouch.cli import cli
from vouch.models import ProposalKind, ProposalStatus
from vouch.proposals import approve
from vouch.storage import KBStore

CONV_ID = "aaaa1111-bbbb-4ccc-8ddd-000000000001"


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    return KBStore.init(tmp_path)


def _msg(
    role: str,
    parts: list[Any],
    *,
    recipient: str | None = None,
    hidden: bool = False,
    content_type: str = "text",
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "author": {"role": role},
        "create_time": 1785136000.0,
        "content": {"content_type": content_type, "parts": parts},
        "metadata": {},
    }
    if hidden:
        msg["metadata"]["is_visually_hidden_from_conversation"] = True
    if recipient is not None:
        msg["recipient"] = recipient
    return msg


def _basic_conversation() -> dict[str, Any]:
    """One conversation exercising every skip rule.

    The canonical chain (root → … → u3) holds two answered exchanges plus a
    dangling "thanks!"; an abandoned sibling branch, a system message, a
    tool-addressed assistant message, and a hidden message must all be
    invisible in the result.
    """
    mapping = {
        "root": {"id": "root", "parent": None, "children": ["sys"], "message": None},
        "sys": {
            "id": "sys", "parent": "root", "children": ["u1"],
            "message": _msg("system", ["you are chatgpt"]),
        },
        "u1": {
            "id": "u1", "parent": "sys", "children": ["a1-old", "a1-tool"],
            "message": _msg("user", ["how do i add a health endpoint to the acme api?"]),
        },
        # a regenerated answer the user abandoned — off the canonical chain
        "a1-old": {
            "id": "a1-old", "parent": "u1", "children": [],
            "message": _msg("assistant", ["ABANDONED DRAFT"]),
        },
        # assistant → tool traffic, not user-visible prose
        "a1-tool": {
            "id": "a1-tool", "parent": "u1", "children": ["a1"],
            "message": _msg("assistant", ["import requests"], recipient="python"),
        },
        "a1": {
            "id": "a1", "parent": "a1-tool", "children": ["hidden"],
            "message": _msg("assistant", ["add a /health route returning 200."]),
        },
        "hidden": {
            "id": "hidden", "parent": "a1", "children": ["u2"],
            "message": _msg("user", ["HIDDEN CONTEXT"], hidden=True),
        },
        # multimodal turn: the image part is skipped, the text part kept
        "u2": {
            "id": "u2", "parent": "hidden", "children": ["a2"],
            "message": _msg(
                "user",
                [{"asset_pointer": "file-service://file-abc"}, "here is the error screenshot"],
                content_type="multimodal_text",
            ),
        },
        "a2": {
            "id": "a2", "parent": "u2", "children": ["u3"],
            "message": _msg("assistant", ["the 500 comes from the missing db url."]),
        },
        # dangling user turn with no answer — dropped
        "u3": {
            "id": "u3", "parent": "a2", "children": [],
            "message": _msg("user", ["thanks!"]),
        },
    }
    return {
        "title": "acme health endpoint",
        "create_time": 1785136000.0,
        "update_time": 1785139600.0,
        "conversation_id": CONV_ID,
        "current_node": "u3",
        "mapping": mapping,
    }


def _empty_conversation() -> dict[str, Any]:
    return {
        "title": "empty",
        "conversation_id": "aaaa1111-bbbb-4ccc-8ddd-000000000002",
        "current_node": "sys",
        "mapping": {
            "sys": {
                "id": "sys", "parent": None, "children": [],
                "message": _msg("system", ["you are chatgpt"]),
            },
        },
    }


def _write_export(tmp_path: Path, conversations: list[dict[str, Any]]) -> Path:
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(conversations), encoding="utf-8")
    return path


# --- parser ----------------------------------------------------------------


def test_parse_pairs_turns_and_skips_noise(tmp_path: Path) -> None:
    export = _write_export(tmp_path, [_basic_conversation()])
    convs = ci.parse_export(export)
    assert len(convs) == 1
    conv = convs[0]
    assert conv.conversation_id == CONV_ID
    assert conv.title == "acme health endpoint"
    assert conv.created_at is not None and conv.created_at.startswith("2026-")
    assert [(e.user, e.assistant) for e in conv.exchanges] == [
        (
            "how do i add a health endpoint to the acme api?",
            "add a /health route returning 200.",
        ),
        ("here is the error screenshot", "the 500 comes from the missing db url."),
    ]
    flat = json.dumps([(e.user, e.assistant) for e in conv.exchanges])
    assert "ABANDONED" not in flat
    assert "import requests" not in flat
    assert "HIDDEN CONTEXT" not in flat
    assert "you are chatgpt" not in flat


def test_parse_merges_consecutive_same_role_turns(tmp_path: Path) -> None:
    raw = {
        "conversation_id": "cccc-1",
        "current_node": "a2",
        "mapping": {
            "u1": {"id": "u1", "parent": None, "children": ["u2"],
                   "message": _msg("user", ["first thought"])},
            "u2": {"id": "u2", "parent": "u1", "children": ["a1"],
                   "message": _msg("user", ["second thought"])},
            "a1": {"id": "a1", "parent": "u2", "children": ["a2"],
                   "message": _msg("assistant", ["part one."])},
            "a2": {"id": "a2", "parent": "a1", "children": [],
                   "message": _msg("assistant", ["part two."])},
        },
    }
    convs = ci.parse_export(_write_export(tmp_path, [raw]))
    assert [(e.user, e.assistant) for e in convs[0].exchanges] == [
        ("first thought\n\nsecond thought", "part one.\n\npart two.")
    ]


def test_parse_falls_back_to_deepest_leaf_without_current_node(
    tmp_path: Path,
) -> None:
    raw = _basic_conversation()
    del raw["current_node"]
    convs = ci.parse_export(_write_export(tmp_path, [raw]))
    assert len(convs[0].exchanges) == 2


def test_parse_zip_export(tmp_path: Path) -> None:
    inner = json.dumps([_basic_conversation()])
    path = tmp_path / "chatgpt-export.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("user.json", "{}")
        zf.writestr("conversations.json", inner)
    convs = ci.parse_export(path)
    assert len(convs) == 1
    assert convs[0].conversation_id == CONV_ID


def test_parse_zip_without_conversations_is_actionable_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "not-an-export.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(ci.ChatGPTImportError, match=r"conversations\.json"):
        ci.parse_export(path)


def test_parse_invalid_json_is_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "conversations.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ci.ChatGPTImportError, match="not valid JSON"):
        ci.parse_export(path)


def test_parse_non_conversation_json_is_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "conversations.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(ci.ChatGPTImportError, match="ChatGPT export"):
        ci.parse_export(path)


def test_parse_oversized_export_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ci, "_MAX_EXPORT_BYTES", 8)
    export = _write_export(tmp_path, [_basic_conversation()])
    with pytest.raises(ci.ChatGPTImportError, match="too large"):
        ci.parse_export(export)


# --- import ----------------------------------------------------------------


def test_import_files_pending_cited_page(store: KBStore, tmp_path: Path) -> None:
    export = _write_export(tmp_path, [_basic_conversation(), _empty_conversation()])
    report = ci.import_export(store, export, generated_at="2026-07-28T00:00:00+00:00")
    assert report["conversations"] == 2
    assert report["imported"] == 1
    assert report["skipped"] == 1  # the empty conversation

    pend = store.list_proposals(ProposalStatus.PENDING)
    assert len(pend) == 1
    pr = pend[0]
    assert pr.kind == ProposalKind.PAGE
    assert pr.proposed_by == ci.CHATGPT_ACTOR
    assert pr.session_id == f"chatgpt-{CONV_ID}"
    assert pr.payload["type"] == "session"
    assert pr.payload["title"] == "chatgpt: acme health endpoint"
    assert pr.payload["id"].startswith("chatgpt-aaaa1111")
    # the page cites the per-conversation source registered from the export
    assert pr.payload["sources"]
    source = store.get_source(pr.payload["sources"][0])
    assert source.locator == f"chatgpt:{CONV_ID}"
    body = pr.payload["body"]
    assert "**you:** how do i add a health endpoint" in body
    assert "**chatgpt:** add a /health route returning 200." in body
    assert "- exchanges: 2" in body
    assert "ABANDONED" not in body
    # a deliberate import is never auto-rejected as capture noise
    assert store.list_proposals(ProposalStatus.REJECTED) == []
    # the review gate stays intact: proposals, not durable pages
    assert store.list_pages() == []


def test_import_respects_vouch_agent_env(
    store: KBStore, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VOUCH_AGENT", "alice-example")
    export = _write_export(tmp_path, [_basic_conversation()])
    ci.import_export(store, export)
    assert store.list_proposals(ProposalStatus.PENDING)[0].proposed_by == "alice-example"


def test_reimport_unchanged_is_noop(store: KBStore, tmp_path: Path) -> None:
    export = _write_export(tmp_path, [_basic_conversation()])
    first = ci.import_export(store, export, generated_at="2026-07-28T00:00:00+00:00")
    second = ci.import_export(store, export, generated_at="2026-07-28T01:00:00+00:00")
    assert second["imported"] == 0 and second["updated"] == 0
    assert second["rows"][0]["reason"] == "unchanged"
    assert second["rows"][0]["proposal_id"] == first["rows"][0]["proposal_id"]
    assert len(store.list_proposals(None)) == 1


def _grown_conversation() -> dict[str, Any]:
    """BASIC plus an answer to the dangling "thanks!" — a later exchange."""
    raw = _basic_conversation()
    raw["mapping"]["u3"]["children"] = ["a3"]
    raw["mapping"]["a3"] = {
        "id": "a3", "parent": "u3", "children": [],
        "message": _msg("assistant", ["anytime — ship it."]),
    }
    raw["current_node"] = "a3"
    return raw


def test_reimport_grown_conversation_refreshes_pending_in_place(
    store: KBStore, tmp_path: Path
) -> None:
    first = ci.import_export(
        store, _write_export(tmp_path, [_basic_conversation()]),
        generated_at="2026-07-28T00:00:00+00:00",
    )
    pid = first["rows"][0]["proposal_id"]
    second = ci.import_export(
        store, _write_export(tmp_path, [_grown_conversation()]),
        generated_at="2026-07-28T01:00:00+00:00",
    )
    assert second["updated"] == 1
    assert second["rows"][0]["proposal_id"] == pid
    proposals = store.list_proposals(None)
    assert len(proposals) == 1
    assert proposals[0].status == ProposalStatus.PENDING
    assert "anytime — ship it." in proposals[0].payload["body"]

    from vouch import audit

    events = [e.event for e in audit.read_events(store.kb_dir)]
    assert "proposal.page.update" in events


def test_decided_proposal_blocks_reimport(store: KBStore, tmp_path: Path) -> None:
    first = ci.import_export(store, _write_export(tmp_path, [_basic_conversation()]))
    pid = first["rows"][0]["proposal_id"]
    approve(store, pid, approved_by="alice-example")
    result = ci.import_export(store, _write_export(tmp_path, [_grown_conversation()]))
    assert result["skipped"] == 1
    assert result["rows"][0]["reason"] == "already-imported"
    # approving a cited page spawns extractor follow-ons (derived_from
    # relations) under the same session id — the page itself stays singular
    pages = [p for p in store.list_proposals(None) if p.kind == ProposalKind.PAGE]
    assert len(pages) == 1
    assert "anytime" not in store.list_pages()[0].body


def test_dry_run_files_nothing(store: KBStore, tmp_path: Path) -> None:
    export = _write_export(tmp_path, [_basic_conversation()])
    report = ci.import_export(store, export, dry_run=True)
    assert report["imported"] == 1  # what a real run would file
    assert report["rows"][0]["dry_run"] is True
    assert store.list_proposals(None) == []


def test_limit_bounds_conversations(store: KBStore, tmp_path: Path) -> None:
    export = _write_export(tmp_path, [_basic_conversation(), _empty_conversation()])
    report = ci.import_export(store, export, limit=1)
    assert report["conversations"] == 1
    assert report["imported"] == 1


def test_long_conversation_body_is_clipped(tmp_path: Path) -> None:
    conv = ci.Conversation(
        conversation_id="cccc-2",
        exchanges=[
            ci.Exchange(user=f"question {i}", assistant=f"answer {i}")
            for i in range(60)
        ],
    )
    body = ci.build_page_body(conv)
    assert "question 49" in body
    assert "question 50" not in body
    assert "10 more exchange(s)" in body


# --- cli -------------------------------------------------------------------


def test_cli_import_chatgpt_json(store: KBStore, tmp_path: Path, monkeypatch) -> None:
    export = _write_export(tmp_path, [_basic_conversation()])
    monkeypatch.chdir(store.kb_dir.parent)
    res = CliRunner().invoke(cli, ["import-chatgpt", str(export), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["imported"] == 1
    assert len(store.list_proposals(ProposalStatus.PENDING)) == 1


def test_cli_import_chatgpt_bad_export_is_clean_error(
    store: KBStore, tmp_path: Path, monkeypatch
) -> None:
    bad = tmp_path / "conversations.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.chdir(store.kb_dir.parent)
    res = CliRunner().invoke(cli, ["import-chatgpt", str(bad)])
    assert res.exit_code != 0
    assert "Error:" in res.output
    assert "Traceback" not in res.output

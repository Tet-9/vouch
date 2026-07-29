"""Import a ChatGPT history export into review-gated session pages.

ChatGPT's data export ships a ``conversations.json`` (inside the ZIP
OpenAI mails out, or extracted) holding every conversation as a branching
``mapping`` tree. ``vouch import chatgpt`` walks each conversation's
canonical branch, pairs every user turn with the assistant turn that
answered it — one exchange per pair, the same unit ditto's importer calls
a memory — and files one PENDING ``session`` page proposal per
conversation, cited to a per-conversation source registered from the
export.

Re-importing the same export is safe: the conversation id is the natural
dedup key. A conversation that grew since the last import refreshes its
still-PENDING proposal in place; an unchanged one is a flat no-op; a
decided proposal is history and blocks re-import regardless. The source
id is the sha256 of the extracted conversation, so identical content
never registers twice.

The export format is not a stable public contract. Parsing is therefore
tolerant — hidden messages, tool traffic, and unknown content types are
skipped — but a file that doesn't look like an export at all degrades to
:class:`ChatGPTImportError` with an actionable message, never a stack
trace.

Never calls ``approve()`` — the review gate stays intact. A human reviews
each conversation with ``vouch review`` like any other write.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import audit
from .models import Proposal, ProposalKind, ProposalStatus
from .proposals import default_scope, propose_page
from .storage import KBStore

# The default proposer when VOUCH_AGENT isn't set. Deliberately NOT one of
# admission's AUTO_CAPTURE_ACTORS: an import is a human choosing to file
# their history, so admission verdicts stay advisory and the pages reach
# review instead of being auto-rejected as capture noise.
CHATGPT_ACTOR = "chatgpt-import"

PAGE_TYPE = "session"

# Mirrors ditto's documented 200 MiB import ceiling — and, like the byte
# caps elsewhere (fetch, codex_rollout), keeps one oversized archive from
# exhausting memory.
_MAX_EXPORT_BYTES = 200 * 1024 * 1024
_MAX_TURN_CHARS = 2_000
_MAX_EXCHANGES_PER_PAGE = 50
_MAX_TITLE_CHARS = 120
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class ChatGPTImportError(RuntimeError):
    """Raised when an export can't be read or doesn't parse as one.

    The CLI layer translates this into a clean ``Error: ...`` line via
    ``_cli_errors``; nothing is written to the KB when it's raised.
    """


@dataclass
class Exchange:
    """One user turn paired with the assistant turn that answered it."""

    user: str
    assistant: str


@dataclass
class Conversation:
    """The import-relevant slice of one exported conversation."""

    conversation_id: str
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    exchanges: list[Exchange] = field(default_factory=list)


def _iso(epoch: Any) -> str | None:
    """An export epoch timestamp as ISO-8601 UTC, or None if unusable."""
    if not isinstance(epoch, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _read_export_bytes(path: Path) -> bytes:
    """The raw ``conversations.json`` bytes from a ZIP or a bare file.

    The size is checked before reading — for a ZIP against the entry's
    declared uncompressed size, so a small archive can't smuggle in an
    oversized (or zip-bombed) payload.
    """
    try:
        is_zip = zipfile.is_zipfile(path)
    except OSError as e:
        raise ChatGPTImportError(f"cannot read export file {path}: {e}") from e
    if is_zip:
        with zipfile.ZipFile(path) as zf:
            infos = [
                i for i in zf.infolist()
                if i.filename.rsplit("/", 1)[-1] == "conversations.json"
            ]
            if not infos:
                raise ChatGPTImportError(
                    f"{path.name} has no conversations.json — this doesn't "
                    "look like a ChatGPT data export ZIP"
                )
            info = infos[0]
            if info.file_size > _MAX_EXPORT_BYTES:
                raise ChatGPTImportError(
                    f"{info.filename} is too large to import "
                    f"({info.file_size} bytes > {_MAX_EXPORT_BYTES} byte limit)"
                )
            return zf.read(info)
    try:
        size = path.stat().st_size
        if size > _MAX_EXPORT_BYTES:
            raise ChatGPTImportError(
                f"{path.name} is too large to import "
                f"({size} bytes > {_MAX_EXPORT_BYTES} byte limit)"
            )
        return path.read_bytes()
    except OSError as e:
        raise ChatGPTImportError(f"cannot read export file {path}: {e}") from e


def _message_turn(msg: Any) -> tuple[str, str] | None:
    """One mapping node's message as ``(role, text)``, or None to skip.

    Keeps visible user/assistant prose; drops system messages, tool
    traffic (assistant messages addressed to a tool rather than the user),
    hidden context, and non-text payloads.
    """
    if not isinstance(msg, dict):
        return None
    author = msg.get("author")
    role = author.get("role") if isinstance(author, dict) else None
    if role not in ("user", "assistant"):
        return None
    meta = msg.get("metadata")
    if isinstance(meta, dict) and meta.get("is_visually_hidden_from_conversation"):
        return None
    recipient = msg.get("recipient")
    if role == "assistant" and recipient not in (None, "all"):
        return None
    content = msg.get("content")
    if not isinstance(content, dict):
        return None
    if content.get("content_type") not in ("text", "multimodal_text"):
        return None
    parts = [
        p.strip() for p in content.get("parts") or []
        if isinstance(p, str) and p.strip()
    ]
    if not parts:
        return None
    return str(role), "\n\n".join(parts)


def _fallback_leaf(mapping: dict[str, Any]) -> str | None:
    """The deepest childless node — the branch tip when current_node is absent."""
    best_id: str | None = None
    best_depth = -1
    for node_id, node in mapping.items():
        if not isinstance(node, dict) or node.get("children"):
            continue
        depth = 0
        cur: str | None = node_id
        seen: set[str] = set()
        while cur in mapping and cur not in seen:
            seen.add(cur)
            parent = mapping[cur].get("parent") if isinstance(mapping[cur], dict) else None
            cur = parent if isinstance(parent, str) else None
            depth += 1
        if depth > best_depth:
            best_id, best_depth = node_id, depth
    return best_id


def _canonical_turns(raw: dict[str, Any]) -> list[tuple[str, str]]:
    """The conversation's canonical branch as ordered ``(role, text)`` turns.

    The export stores every edit/regeneration as a sibling branch; only the
    chain from ``current_node`` up to the root is the conversation the user
    actually kept, so abandoned branches never leak into the import.
    """
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict):
        return []
    node_id = raw.get("current_node")
    if not isinstance(node_id, str) or node_id not in mapping:
        node_id = _fallback_leaf(mapping)
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id]
        if not isinstance(node, dict):
            break
        chain.append(node)
        parent = node.get("parent")
        node_id = parent if isinstance(parent, str) else None
    chain.reverse()
    turns: list[tuple[str, str]] = []
    for node in chain:
        turn = _message_turn(node.get("message"))
        if turn is not None:
            turns.append(turn)
    return turns


def _pair_turns(turns: list[tuple[str, str]]) -> list[Exchange]:
    """Pair each user turn with the assistant turn that answered it.

    Consecutive same-role turns merge into one side of the pair; a trailing
    user turn with no answer is dropped — an unanswered prompt on its own
    carries no durable exchange.
    """
    exchanges: list[Exchange] = []
    pending_user: str | None = None
    for role, text in turns:
        if role == "user":
            pending_user = text if pending_user is None else f"{pending_user}\n\n{text}"
        elif pending_user is not None:
            exchanges.append(Exchange(user=pending_user, assistant=text))
            pending_user = None
        elif exchanges:
            last = exchanges[-1]
            last.assistant = f"{last.assistant}\n\n{text}"
    return exchanges


def _parse_conversation(raw: Any) -> Conversation | None:
    if not isinstance(raw, dict):
        return None
    conv_id = raw.get("conversation_id") or raw.get("id")
    if not isinstance(conv_id, str) or not conv_id.strip():
        return None
    title = raw.get("title")
    return Conversation(
        conversation_id=conv_id.strip(),
        title=title.strip() if isinstance(title, str) and title.strip() else None,
        created_at=_iso(raw.get("create_time")),
        updated_at=_iso(raw.get("update_time")),
        exchanges=_pair_turns(_canonical_turns(raw)),
    )


def parse_export(path: Path) -> list[Conversation]:
    """Parse a ChatGPT export (ZIP or conversations.json) into conversations.

    Conversations keep the export's own order (newest first in OpenAI's
    exports). Entries with no id are skipped; a file that isn't JSON, or
    whose JSON isn't conversation-shaped, raises :class:`ChatGPTImportError`.
    """
    content = _read_export_bytes(path)
    try:
        data = json.loads(content.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ChatGPTImportError(
            f"{path.name}: conversations.json is not valid JSON ({e})"
        ) from e
    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        data = data["conversations"]
    if not isinstance(data, list):
        raise ChatGPTImportError(
            f"{path.name}: expected a JSON array of conversations — this "
            "doesn't look like a ChatGPT export, or its schema has drifted"
        )
    out: list[Conversation] = []
    for raw in data:
        conv = _parse_conversation(raw)
        if conv is not None:
            out.append(conv)
    return out


def _clip(text: str) -> str:
    collapsed = text.strip()
    if len(collapsed) > _MAX_TURN_CHARS:
        collapsed = collapsed[: _MAX_TURN_CHARS - 1].rstrip() + "…"
    return collapsed


def session_key(conversation_id: str) -> str:
    """The session id one conversation dedups on, across every re-import."""
    return f"chatgpt-{conversation_id}"


def _page_slug(conversation_id: str) -> str:
    slug = _SLUG_RE.sub("-", conversation_id.lower()).strip("-")
    return f"chatgpt-{slug}"[:80]


def build_page_title(conv: Conversation) -> str:
    label = conv.title
    if not label and conv.exchanges:
        first = " ".join(conv.exchanges[0].user.split())
        label = first[:60].rstrip() + ("…" if len(first) > 60 else "")
    label = label or "untitled conversation"
    title = f"chatgpt: {label}"
    if len(title) > _MAX_TITLE_CHARS:
        title = title[: _MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


def build_page_body(conv: Conversation, *, generated_at: str | None = None) -> str:
    """Render the paired exchanges as a session-page body.

    Long turns and long conversations are clipped for review legibility —
    the cited source keeps the full text, the page is the readable card.
    """
    lines: list[str] = []
    if generated_at:
        lines.append(f"- imported: {generated_at}")
    lines.append(f"- conversation: {conv.conversation_id}")
    if conv.created_at:
        lines.append(f"- started: {conv.created_at}")
    if conv.updated_at:
        lines.append(f"- last-active: {conv.updated_at}")
    lines.append(f"- exchanges: {len(conv.exchanges)}")
    lines.extend(["", "## exchanges", ""])
    shown = conv.exchanges[:_MAX_EXCHANGES_PER_PAGE]
    for ex in shown:
        lines.append(f"**you:** {_clip(ex.user)}")
        lines.append("")
        lines.append(f"**chatgpt:** {_clip(ex.assistant)}")
        lines.append("")
    hidden = len(conv.exchanges) - len(shown)
    if hidden > 0:
        lines.append(
            f"(… {hidden} more exchange(s) — full conversation in the cited source)"
        )
    return "\n".join(lines).rstrip() + "\n"


def _source_content(conv: Conversation) -> bytes:
    """The conversation's full extracted text as deterministic JSON bytes.

    Deterministic serialization means an unchanged conversation hashes to
    the same source id on every import — ``put_source`` dedups on content,
    so re-imports never pile up copies.
    """
    payload = {
        "conversation_id": conv.conversation_id,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "exchanges": [
            {"user": ex.user, "assistant": ex.assistant} for ex in conv.exchanges
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    )


def _find_existing_page(store: KBStore, session_id: str) -> Proposal | None:
    """The page proposal (any status) already filed for this conversation.

    Filtered to PAGE kind: approving an imported page can spawn follow-on
    proposals (e.g. the extractor's ``derived_from`` relation) under the
    same session id, and those must never be mistaken for the page when a
    re-import looks for its dedup target.
    """
    for proposal in store.list_proposals(None):
        if proposal.kind == ProposalKind.PAGE and proposal.session_id == session_id:
            return proposal
    return None


def _comparable_body(body: str) -> str:
    """The page body minus its import timestamp, so re-importing an
    unchanged conversation compares equal across runs."""
    return "\n".join(
        line for line in body.splitlines() if not line.startswith("- imported:")
    )


def import_export(
    store: KBStore,
    path: Path,
    *,
    actor: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Import one export into PENDING session-page proposals. No ``approve()``.

    One proposal per conversation, deduped on the conversation id: a
    decided proposal blocks re-import, a still-PENDING one refreshes in
    place when the conversation grew, and an unchanged conversation is a
    no-op. ``limit`` bounds how many conversations are considered, in
    export order. With ``dry_run`` nothing is written — the report shows
    what a real run would file, ditto's preview step as a flag.
    """
    conversations = parse_export(path)
    if limit is not None and limit >= 0:
        conversations = conversations[:limit]
    resolved_actor = actor or os.environ.get("VOUCH_AGENT") or CHATGPT_ACTOR

    rows: list[dict[str, Any]] = []
    counts = {"imported": 0, "updated": 0, "skipped": 0}
    for conv in conversations:
        title = build_page_title(conv)
        row: dict[str, Any] = {
            "session_id": session_key(conv.conversation_id),
            "title": title,
        }
        if not conv.exchanges:
            row.update(action="skipped", reason="no exchanges")
            counts["skipped"] += 1
            rows.append(row)
            continue
        existing = _find_existing_page(store, row["session_id"])
        if existing is not None and existing.status != ProposalStatus.PENDING:
            row.update(
                action="skipped", reason="already-imported", proposal_id=existing.id
            )
            counts["skipped"] += 1
            rows.append(row)
            continue
        body = build_page_body(conv, generated_at=generated_at)
        if existing is not None and _comparable_body(body) == _comparable_body(
            str(existing.payload.get("body", ""))
        ):
            row.update(action="skipped", reason="unchanged", proposal_id=existing.id)
            counts["skipped"] += 1
            rows.append(row)
            continue
        if dry_run:
            action = "updated" if existing is not None else "imported"
            row.update(action=action, dry_run=True)
            counts[action] += 1
            rows.append(row)
            continue
        source = store.put_source(
            _source_content(conv),
            title=title,
            locator=f"chatgpt:{conv.conversation_id}",
            media_type="application/json",
            tags=["chatgpt-import"],
            scope=default_scope(store),
        )
        if existing is not None:
            refreshed = existing.model_copy(deep=True)
            refreshed.payload["title"] = title
            refreshed.payload["body"] = body
            refreshed.payload["sources"] = [source.id]
            store.update_proposal(refreshed)
            audit.log_event(
                store.kb_dir,
                event="proposal.page.update",
                actor=resolved_actor,
                object_ids=[existing.id],
                data={
                    "reason": "chatgpt re-import",
                    "exchanges": len(conv.exchanges),
                },
            )
            row.update(action="updated", proposal_id=existing.id)
            counts["updated"] += 1
        else:
            proposal = propose_page(
                store,
                title=title,
                body=body,
                page_type=PAGE_TYPE,
                source_ids=[source.id],
                proposed_by=resolved_actor,
                session_id=row["session_id"],
                slug_hint=_page_slug(conv.conversation_id),
                rationale="imported chatgpt conversation",
            )
            row.update(action="imported", proposal_id=proposal.id)
            counts["imported"] += 1
        rows.append(row)

    return {
        "conversations": len(conversations),
        "imported": counts["imported"],
        "updated": counts["updated"],
        "skipped": counts["skipped"],
        "dry_run": dry_run,
        "rows": rows,
    }

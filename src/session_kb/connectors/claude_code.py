"""Claude Code connector: native session jsonl → canonical full-turn records.

The L0→L1 mapping for Claude Code. Reads a native `.jsonl` transcript and emits
canonical records (``schema.py``). Unlike a prompt-only analytics extractor (user
messages only), this is the *full-turn* connector — user + agent + tool — so it
serves both the prompt-analytics consumer and the full-turn KB consumer.

Pure mapping, no scrub
----------------------
This connector emits **verbatim** (unscrubbed) ``message`` text. The mandatory
secret scrub is a separate ingest stage (``connector → scrub → chunk → embed``):
the scrub stage redacts ``message``, sets ``redacted`` / ``scrub_rules_version``,
and **recomputes** ``content_hash`` before anything is written to L0/L1. So
``content_hash`` always matches the record's *current* message at every stage.

Native quirks handled
----------------------
- A Claude Code ``type="user"`` line is **not** always a user turn: when its
  ``message.content`` carries ``tool_result`` blocks (or the line has
  ``toolUseResult``), it is tool output → ``actor="tool"`` and it does **not**
  open a new exchange.
- ``type="assistant"`` ``tool_use`` blocks become ``tool_calls``; they contribute
  no ``message`` text (the text blocks do).
- Non-conversational line types (attachment / custom-title / last-prompt /
  pr-link / queue-operation) are skipped.
- Native fidelity (``parentUuid`` / ``isSidechain`` / ``isMeta`` / ``requestId`` /
  ``version`` / ``toolUseResult``) is preserved under ``ext["claude_code"]``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..schema import RawPtr, SessionRecord, Source, ToolCall, TurnRecord

CONNECTOR_VERSION = "0.1.0"
HARNESS = "claude-code"
PROVIDER = "anthropic"

#: native line types that carry conversation turns; everything else is metadata.
_TURN_TYPES = frozenset({"user", "assistant"})

#: Claude Code injects non-prompt text into the actor=user stream wrapped in these
#: markers (slash-command envelopes, local-command stdout/caveats, interrupt and
#: continuation notices). A user turn whose text starts with one of these — or
#: that carries ``isMeta`` — is harness ``system`` text, not a human prompt.
#: NOTE: remote-control heartbeats ("Reply with exactly: OK", "ping") arrive as
#: bare user text with no marker, so they stay ``prompt`` here and are a job for
#: an analysis-layer heuristic — the connector only classifies what the harness
#: structurally marks.
_SYSTEM_USER_PREFIXES = (
    "<command-name>",
    "<local-command-",
    "[Request interrupted",
    "This session is being continued",
)


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> list[dict[str, Any]]:
    """Parse a native jsonl transcript, skipping blank lines."""
    entries: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _text_from_content(content: Any) -> str:
    """Flatten native message ``content`` to plain text (tool_use blocks omitted)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_result":
            parts.append(_text_from_content(block.get("content", "")))
    return "\n".join(p for p in parts if p)


def _is_tool_result(message: dict[str, Any], entry: dict[str, Any]) -> bool:
    """True when a ``type="user"`` line is actually tool output, not a user turn."""
    if entry.get("toolUseResult") is not None:
        return True
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _message_class(actor: str, text: str, entry: dict[str, Any]) -> str:
    """Classify a turn's provenance (see schema ``MessageClass``).

    ``actor`` already separates agent/tool; the work here is splitting the
    user stream into genuine ``prompt`` vs harness-injected ``system`` text.
    """
    if actor == "agent":
        return "response"
    if actor == "tool":
        return "tool_result"
    if entry.get("isMeta") or text.startswith(_SYSTEM_USER_PREFIXES):
        return "system"
    return "prompt"


def _tool_call_id(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return block.get("tool_use_id")
    return None


def _tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    calls: list[ToolCall] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            calls.append(
                ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}) or {},
                )
            )
    return calls


def _ext(entry: dict[str, Any]) -> dict[str, Any]:
    cc: dict[str, Any] = {}
    for src_key, dst_key in (
        ("parentUuid", "parent_uuid"),
        ("isSidechain", "is_sidechain"),
        ("isMeta", "is_meta"),
        ("requestId", "request_id"),
        ("version", "version"),
    ):
        value = entry.get(src_key)
        if value is not None:
            cc[dst_key] = value
    if entry.get("toolUseResult") is not None:
        cc["tool_use_result"] = entry["toolUseResult"]
    return {"claude_code": cc} if cc else {}


def iter_turns(path: Path, *, connector_version: str = CONNECTOR_VERSION) -> Iterator[TurnRecord]:
    """Yield canonical ``TurnRecord``s (verbatim message) from a native transcript."""
    seq = 0
    exchange_n = 0
    for entry in _load(path):
        if entry.get("type") not in _TURN_TYPES:
            continue
        message = entry.get("message") or {}

        if entry["type"] == "assistant":
            actor = "agent"
        elif _is_tool_result(message, entry):
            actor = "tool"
        else:
            actor = "user"
            exchange_n += 1
        if exchange_n == 0:
            # transcript opened with a non-user turn; anchor it to the first exchange
            exchange_n = 1

        session_id = entry.get("sessionId", "")
        text = _text_from_content(message.get("content"))
        usage = message.get("usage") or {}
        seq += 1

        yield TurnRecord(
            session_id=session_id,
            seq=seq,
            exchange_id=f"{session_id}:x{exchange_n}",
            actor=actor,
            message_class=_message_class(actor, text, entry),
            message=text,
            content_hash=_content_hash(text),
            source=Source(
                harness=HARNESS,
                connector_version=connector_version,
                provider=PROVIDER,
                model=message.get("model") if actor == "agent" else None,
            ),
            raw_ptr=RawPtr(uuids=[entry["uuid"]] if entry.get("uuid") else []),
            ts=entry["timestamp"],
            parent_id=entry.get("parentUuid"),
            cwd=entry.get("cwd"),
            git_branch=entry.get("gitBranch"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            tool_calls=_tool_calls(message) if actor == "agent" else [],
            tool_call_id=_tool_call_id(message) if actor == "tool" else None,
            ext=_ext(entry),
        )


def read_session(
    path: Path, *, host: str, connector_version: str = CONNECTOR_VERSION
) -> SessionRecord:
    """Build the session manifest. ``host`` comes from per-host config (#854)."""
    entries = [e for e in _load(path) if e.get("type") in _TURN_TYPES]
    if not entries:
        raise ValueError(f"no conversation turns in {path}")
    first, last = entries[0], entries[-1]
    model = next(
        (e.get("message", {}).get("model") for e in entries if e["type"] == "assistant"), None
    )
    return SessionRecord(
        session_id=first.get("sessionId", ""),
        host=host,
        source=Source(
            harness=HARNESS, connector_version=connector_version, provider=PROVIDER, model=model
        ),
        cwd=first.get("cwd"),
        git_branch=first.get("gitBranch"),
        started_at=first["timestamp"],
        ended_at=last["timestamp"],
        turn_count=len(entries),
        raw_ptr=RawPtr(uuids=[first["uuid"]] if first.get("uuid") else []),
        cursor=last.get("uuid"),
    )

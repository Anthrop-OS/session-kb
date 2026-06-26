"""Per-exchange, length-gated chunking.

Exchange = a user message plus ensuing agent/tool activity until the next user
message. Turns are per-message; the *chunk* is per-exchange and is the embedding
unit. Exchanges within the configurable token cap are embedded verbatim
(``embed_source="raw"``); larger ones are summarized by a cheap model first, then
the summary is embedded (``embed_source="summary"``).

This milestone implements the **raw path** end-to-end. Summarization needs a
model and is therefore injected: pass a ``summarizer`` callable to handle
over-cap exchanges. With no summarizer, an over-cap exchange raises rather than
being silently truncated or mislabeled — the deferred boundary is loud, not
quiet. Embedding the chunk text into vectors is a separate, later stage
(``embed.py``); the chunk only records *what text would be embedded* and its
hash, so a rebuild never re-runs inference.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Iterator

from .schema import ChunkRecord, TurnRecord

DEFAULT_SUMMARY_THRESHOLD_TOKENS = 2048

#: A summarizer maps over-cap exchange text → a shorter summary to embed.
Summarizer = Callable[[str], str]


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate (~4 chars/token).

    Deliberately a heuristic: the cap only decides raw-vs-summarize, so an
    approximate count is fine and keeps the chunker free of a tokenizer
    dependency. Embedding/summary stages do their own exact accounting.
    """
    return len(text) // 4


def _embed_text(turns: list[TurnRecord]) -> str:
    """The exact text an exchange contributes to the index.

    Actor-tagged, blank-line separated, in ``seq`` order. Turns with no textual
    message (e.g. an agent turn that is pure tool_use) contribute nothing, so
    they are dropped rather than emitting a bare ``agent:`` line.
    """
    parts = [f"{t.actor}: {t.message.strip()}" for t in turns if t.message.strip()]
    return "\n\n".join(parts)


def _group_by_exchange(turns: Iterable[TurnRecord]) -> Iterator[list[TurnRecord]]:
    """Group consecutive turns by ``exchange_id``, preserving first-seen order.

    The connector emits turns in ``seq`` order with one ``exchange_id`` per
    user boundary, so grouping is a single linear pass — no global sort.
    """
    current_id: str | None = None
    bucket: list[TurnRecord] = []
    for turn in turns:
        if turn.exchange_id != current_id:
            if bucket:
                yield bucket
            bucket = []
            current_id = turn.exchange_id
        bucket.append(turn)
    if bucket:
        yield bucket


def chunk(
    turns: Iterable[TurnRecord],
    summary_threshold_tokens: int = DEFAULT_SUMMARY_THRESHOLD_TOKENS,
    summarizer: Summarizer | None = None,
) -> Iterator[ChunkRecord]:
    """Yield one ``ChunkRecord`` per exchange.

    Under the cap → ``embed_source="raw"`` over the concatenated verbatim turns.
    Over the cap → ``embed_source="summary"`` using ``summarizer``; without one,
    raises ``NotImplementedError`` (the summary stage is deferred, never faked).

    The ``content_hash`` is the sha256 of the exact embedded text — the raw
    concatenation or the summary — so it ties 1:1 to the ``EmbeddingRecord`` and
    anchors inference-free rebuilds.
    """
    for bucket in _group_by_exchange(turns):
        raw_text = _embed_text(bucket)
        exchange_id = bucket[0].exchange_id
        session_id = bucket[0].session_id

        if _estimate_tokens(raw_text) <= summary_threshold_tokens:
            embedded, embed_source, summary = raw_text, "raw", None
        elif summarizer is not None:
            summary = summarizer(raw_text)
            embedded, embed_source = summary, "summary"
        else:
            raise NotImplementedError(
                f"exchange {exchange_id} exceeds {summary_threshold_tokens} tokens; "
                "pass summarizer= to chunk over-cap exchanges (summary stage deferred)"
            )

        yield ChunkRecord(
            exchange_id=exchange_id,
            session_id=session_id,
            embed_source=embed_source,
            content_hash=_content_hash(embedded),
            summary=summary,
        )

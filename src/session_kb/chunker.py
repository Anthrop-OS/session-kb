"""Per-exchange, length-gated chunking.

Exchange = a user message plus ensuing agent/tool activity until the next user
message. Records are per-message; embeddings are per-exchange. Exchanges within
the configurable token cap are embedded verbatim; larger ones are summarized by
a cheap model first, then the summary is embedded.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .schema import TurnRecord

DEFAULT_SUMMARY_THRESHOLD_TOKENS = 2048


def chunk(
    turns: Iterable[TurnRecord],
    summary_threshold_tokens: int = DEFAULT_SUMMARY_THRESHOLD_TOKENS,
) -> Iterator[TurnRecord]:
    raise NotImplementedError("milestone: length-gated chunker")

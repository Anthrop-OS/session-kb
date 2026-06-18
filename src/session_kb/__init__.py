"""session-kb — harness-agnostic archival & retrieval for AI coding sessions.

Pipeline: connector → canonical turn records → chunk + embed → sqlite (FTS5 + vec).
This package is tool code only; it never stores or commits session content.
"""

__version__ = "0.0.0"

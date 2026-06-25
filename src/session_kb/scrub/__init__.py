"""Secret scrub — magnitude reduction layer (NOT the security boundary).

Provides a pluggable ScrubProvider protocol, a batteries-included builtin
provider, optional gitleaks/trufflehog wrappers, and a composite that unions
multiple providers. User-supplied pattern files are loaded via --extra-patterns.
"""

from .builtin import BuiltinScrubProvider
from .composite import CompositeScrubProvider
from .interface import Finding, ScrubProvider

__all__ = [
    "BuiltinScrubProvider",
    "CompositeScrubProvider",
    "Finding",
    "ScrubProvider",
]

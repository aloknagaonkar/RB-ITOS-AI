from __future__ import annotations


class RedBarV2CanonicalError(Exception):
    """Base exception for canonical Red Bar V2 resolution services."""


class LegacyMappingError(RedBarV2CanonicalError, ValueError):
    """Raised when legacy V2 data cannot be mapped without guessing."""


class CanonicalResolutionError(RedBarV2CanonicalError):
    """Raised when canonical sections cannot be assembled consistently."""

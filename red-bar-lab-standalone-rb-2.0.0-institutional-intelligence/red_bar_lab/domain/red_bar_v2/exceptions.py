class RedBarV2DomainError(Exception):
    """Base exception for canonical Red Bar V2 domain contracts."""


class DomainValidationError(RedBarV2DomainError, ValueError):
    """Raised when a canonical domain object violates an invariant."""


class UnsupportedSchemaVersionError(RedBarV2DomainError):
    """Raised when serialized data uses an unsupported schema version."""


class BundleIdentityError(RedBarV2DomainError):
    """Raised when bundle identity does not match canonical fields."""

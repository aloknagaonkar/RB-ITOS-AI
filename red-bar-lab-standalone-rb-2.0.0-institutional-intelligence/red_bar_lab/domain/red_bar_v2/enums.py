from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility implementation for Python 3.10."""


class RedBarV2Section1Outcome(StrEnum):
    INPUTS_NOT_READY = "INPUTS_NOT_READY"
    CANDLES_STALE = "CANDLES_STALE"
    SESSION_MISALIGNED = "SESSION_MISALIGNED"
    REFERENCE_WAITING = "REFERENCE_WAITING"
    REFERENCE_INVALID = "REFERENCE_INVALID"
    FUTURES_NOT_READY = "FUTURES_NOT_READY"
    VWAP_SOURCE_NOT_READY = "VWAP_SOURCE_NOT_READY"
    REFERENCE_READY = "REFERENCE_READY"


class RedBarV2State(StrEnum):
    REFERENCE_NOT_READY = "REFERENCE_NOT_READY"
    REFERENCE_READY = "REFERENCE_READY"
    SIGNAL_WAITING = "SIGNAL_WAITING"
    PROVISIONAL_BULLISH = "PROVISIONAL_BULLISH"
    PROVISIONAL_BEARISH = "PROVISIONAL_BEARISH"
    CONFIRMED_BULLISH = "CONFIRMED_BULLISH"
    CONFIRMED_BEARISH = "CONFIRMED_BEARISH"


class EntryType(StrEnum):
    """Which reference authorised the entry, and therefore which gates applied.

    INITIAL and REVERSAL are both judged against the red bar: INITIAL is the
    day's first entry, REVERSAL a re-entry once price is back inside the red
    bar's band. WORKING is judged against the deputy reference that governs the
    space *outside* that band, and is the one path that consults no futures VWAP.
    """

    INITIAL = "INITIAL"
    REVERSAL = "REVERSAL"
    WORKING = "WORKING"



class Direction(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class OptionSide(StrEnum):
    CE = "CE"
    PE = "PE"


class TrendStrength(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"


class ContextStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISALIGNED = "MISALIGNED"
    UNAVAILABLE = "UNAVAILABLE"


class AdmissionOutcome(StrEnum):
    WAITING = "WAITING"
    ALLOWED = "ALLOWED"
    REJECTED = "REJECTED"


class BundleLifecycleStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    CONSUMED = "CONSUMED"
    REJECTED = "REJECTED"

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional


class MidpointFamily(str, Enum):
    A = "A"
    B = "B"
    E = "E"
    C = "C"
    D = "D"
    PM_B = "PM_B"
    PM_E = "PM_E"


class MidpointMode(str, Enum):
    SHADOW = "SHADOW"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"


class MidpointShadowState(str, Enum):
    IDLE = "IDLE"
    B_CANDIDATE = "B_CANDIDATE"
    ACTIVE = "ACTIVE"
    RUNNER_STRENGTHENING = "RUNNER_STRENGTHENING"
    DEGRADED = "DEGRADED"
    CAP20_RESCUED = "CAP20_RESCUED"
    REENTERED = "REENTERED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class MidpointSignal:
    strategy: str
    family: MidpointFamily
    direction: str
    timestamp: datetime
    state: MidpointShadowState
    reason: str
    underlying_points: Optional[float] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

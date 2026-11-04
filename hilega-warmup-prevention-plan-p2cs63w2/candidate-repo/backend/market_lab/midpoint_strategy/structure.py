from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Direction = Literal["BULLISH", "BEARISH"]
ReferenceType = Literal["RED", "GREEN"]


@dataclass(frozen=True)
class ReferenceStructure:
    session_date: str
    reference_type: ReferenceType
    start_timestamp: str
    end_timestamp: str
    high: float
    low: float

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def boundary(self) -> float:
        # RED bearish continuation breaks the low.
        # GREEN bullish continuation breaks the high.
        return self.low if self.reference_type == "RED" else self.high

    @property
    def direction(self) -> Direction:
        return "BEARISH" if self.reference_type == "RED" else "BULLISH"


def midpoint_broken(reference: ReferenceStructure, close: float) -> bool:
    if reference.reference_type == "RED":
        return close < reference.midpoint
    return close > reference.midpoint


def boundary_broken(reference: ReferenceStructure, close: float) -> bool:
    if reference.reference_type == "RED":
        return close < reference.low
    return close > reference.high


def structure_still_valid(reference: ReferenceStructure, close: float) -> bool:
    # Canonical Family-B delayed-confirmation lifecycle.
    if reference.reference_type == "RED":
        return close <= reference.midpoint
    return close >= reference.midpoint

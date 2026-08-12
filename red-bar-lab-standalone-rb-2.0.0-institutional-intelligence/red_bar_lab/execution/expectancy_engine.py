"""RB-1.0.0 expectancy model notes.

The live implementation is integrated into InstitutionalExecutionCommittee so
there is one execution authority. This module exposes the core expectancy
formula for tests/research utilities without creating a second decision engine.
"""
from __future__ import annotations


def expectancy_pct(win_probability_pct: float, expected_win_pct: float, expected_loss_pct: float) -> float:
    p = max(0.0, min(1.0, float(win_probability_pct) / 100.0))
    win = max(0.0, float(expected_win_pct))
    loss = max(0.0, float(expected_loss_pct))
    return round(p * win - (1.0 - p) * loss, 3)

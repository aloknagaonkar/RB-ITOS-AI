#!/usr/bin/env python3

"""
Evaluation-only adapter for OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1.

Purpose:
    Run the already-frozen midpoint framework on OOS_E/F/G after rule
    discovery is complete.

Important:
    - Does NOT modify opening_candle_midpoint_framework_v1.py.
    - Does NOT change build_event(), midpoint logic, boundary logic,
      reclaim logic, or outcome classification.
    - Only changes which block names the existing CLI accepts for this
      post-freeze validation run.
"""

from market_lab import opening_candle_midpoint_framework_v1 as framework


def main() -> None:
    framework.ALLOWED_BLOCKS = {
        "OOS_E",
        "OOS_F",
        "OOS_G",
    }

    framework.main()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

LIVE = Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"STOP: {label}: expected exactly one anchor, found {n}")
    return text.replace(old, new, 1)


def patch_live(s: str) -> str:
    old1 = (
        "        if terminal_this_minute:\n"
        "            return\n"
        "\n"
        "        for ref_type in (\"RED\", \"GREEN\"):\n"
    )
    new1 = (
        "        # V57.1 parity rule:\n"
        "        # A structural terminal does not suppress opposite-structure\n"
        "        # observation on the same completed 1m candle. Same-candle\n"
        "        # reversal entry remains prohibited below.\n"
        "        for ref_type in (\"RED\", \"GREEN\"):\n"
    )
    s = replace_once(s, old1, new1, "terminal early-return")

    old2 = (
        "                if decision.owner == MidpointFamily.E.value:\n"
        "                    if not self.config.family_e_enabled:\n"
    )
    new2 = (
        "                if decision.owner == MidpointFamily.E.value:\n"
        "                    if terminal_this_minute:\n"
        "                        self.engine._audit(\n"
        "                            runtime=rr.runtime,\n"
        "                            timestamp=obs.timestamp,\n"
        "                            event_type=\"E_ENTRY_BLOCKED\",\n"
        "                            direction=rr.reference.direction,\n"
        "                            result=\"NO_ENTRY\",\n"
        "                            reason=\"SAME_CANDLE_REVERSAL_BLOCKED\",\n"
        "                            observation=obs,\n"
        "                            evidence={\n"
        "                                \"family_selected\": \"E\",\n"
        "                                \"same_candle_structural_terminal\": True,\n"
        "                                \"order_sent\": False,\n"
        "                            },\n"
        "                        )\n"
        "                        continue\n"
        "\n"
        "                    if not self.config.family_e_enabled:\n"
    )
    s = replace_once(s, old2, new2, "E same-candle reversal guard")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not LIVE.exists():
        raise SystemExit(f"STOP: missing {LIVE}")

    before = LIVE.read_text()
    after = patch_live(before)
    print(f"{LIVE}: changed={before != after}")

    if args.apply:
        backup = LIVE.with_suffix(LIVE.suffix + ".pre-v57-1.bak")
        if not backup.exists():
            backup.write_text(before)
        LIVE.write_text(after)

    print("mode:", "APPLIED" if args.apply else "DRY_RUN")
    print("No B/E selection threshold changed.")
    print("Same-candle reversal entry remains blocked.")
    print("Observation-only safety unchanged.")


if __name__ == "__main__":
    main()

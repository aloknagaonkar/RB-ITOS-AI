#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = ROOT / "backend/market_lab/midpoint_strategy/structure.py"
SHADOW = ROOT / "backend/market_lab/midpoint_strategy/family_b_shadow.py"
RUNTIME = ROOT / "backend/market_lab/midpoint_strategy/runtime.py"
LIVE = ROOT / "backend/market_lab/midpoint_strategy/live_shadow_v1.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"STOP: expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def patch_structure(text: str) -> str:
    old = """def structure_still_valid(reference: ReferenceStructure, close: float) -> bool:
    # Frozen Family-B lifecycle constraint:
    # while waiting for delayed confirmation the same directional structure
    # must remain valid. For the first shadow implementation we preserve the
    # original full-range opposite-side invalidation.
    if reference.reference_type == "RED":
        return close <= reference.high
    return close >= reference.low
"""
    new = """def structure_still_valid(reference: ReferenceStructure, close: float) -> bool:
    # Canonical Family-B delayed-confirmation lifecycle:
    # BEARISH remains valid while close <= midpoint.
    # BULLISH remains valid while close >= midpoint.
    if reference.reference_type == "RED":
        return close <= reference.midpoint
    return close >= reference.midpoint
"""
    if new in text:
        return text
    return replace_once(text, old, new, "canonical structure_still_valid")


def patch_shadow(text: str) -> str:
    field_old = """    reentry_timestamp: Optional[datetime] = None
    reentry_count: int = 0

    state: MidpointShadowState = MidpointShadowState.ACTIVE
"""
    field_new = """    reentry_timestamp: Optional[datetime] = None
    reentry_count: int = 0

    # CAP20 is decided only on the first eligible post-recovery rebreak.
    cap20_rebreak_evaluated: bool = False

    state: MidpointShadowState = MidpointShadowState.ACTIVE
"""
    if "cap20_rebreak_evaluated: bool = False" not in text:
        text = replace_once(text, field_old, field_new, "CAP20 state field")

    old = """        if timestamp < rt.recovery_timestamp + timedelta(minutes=10):
            return None

        # Frozen CAP20 rescue:
        # after recovery, first rebreak below degraded target;
        # rescue only when captured directional points <= +20.
        if (
            current_directional_move < rt.degraded_target_move
            and current_directional_points <= 20
        ):
            rt.rescue_timestamp = timestamp
            rt.rescue_directional_points = current_directional_points
            rt.state = MidpointShadowState.CAP20_RESCUED
            return MidpointSignal(
                strategy=self.config.strategy_name,
                family=MidpointFamily.B,
                direction=rt.direction,
                timestamp=timestamp,
                state=rt.state,
                reason="CAP20_RESCUE",
                underlying_points=current_directional_points,
                metadata={
                    "degraded_target_move": rt.degraded_target_move,
                },
            )

        return None
"""
    new = """        if timestamp < rt.recovery_timestamp + timedelta(minutes=10):
            return None

        if rt.cap20_rebreak_evaluated:
            return None

        # Canonical CAP20: after recovery+10m, the FIRST close rebreak below
        # degraded target consumes the rescue opportunity.
        if current_directional_move < rt.degraded_target_move:
            rt.cap20_rebreak_evaluated = True
            if current_directional_points <= 20:
                rt.rescue_timestamp = timestamp
                rt.rescue_directional_points = current_directional_points
                rt.state = MidpointShadowState.CAP20_RESCUED
                return MidpointSignal(
                    strategy=self.config.strategy_name,
                    family=MidpointFamily.B,
                    direction=rt.direction,
                    timestamp=timestamp,
                    state=rt.state,
                    reason="CAP20_RESCUE",
                    underlying_points=current_directional_points,
                    metadata={
                        "degraded_target_move": rt.degraded_target_move,
                    },
                )

        return None
"""
    if new not in text:
        text = replace_once(text, old, new, "canonical CAP20 first-rebreak rule")
    return text


def patch_runtime(text: str) -> str:
    old = """        sig = self.manager.maybe_cap20_rescue(
            rt,
            datetime.fromisoformat(obs.timestamp),
            current_directional_points=current_points,
            current_directional_move=current_move,
        )

        if sig is None:
"""
    new = """        rebreak_evaluated_before = rt.cap20_rebreak_evaluated

        sig = self.manager.maybe_cap20_rescue(
            rt,
            datetime.fromisoformat(obs.timestamp),
            current_directional_points=current_points,
            current_directional_move=current_move,
        )

        if sig is None:
"""
    if "rebreak_evaluated_before = rt.cap20_rebreak_evaluated" not in text:
        text = replace_once(text, old, new, "CAP20 audit pre-state")

    old_reason = """                result="NO_ACTION",
                reason="CAP20_CONDITIONS_NOT_ALL_MET",
"""
    new_reason = """                result="NO_ACTION",
                reason=(
                    "CAP20_FIRST_REBREAK_ABOVE_20_NO_RESCUE"
                    if (
                        not rebreak_evaluated_before
                        and rt.cap20_rebreak_evaluated
                        and rt.degraded_target_move is not None
                        and current_move < rt.degraded_target_move
                        and current_points > 20
                    )
                    else "CAP20_CONDITIONS_NOT_ALL_MET"
                ),
"""
    if "CAP20_FIRST_REBREAK_ABOVE_20_NO_RESCUE" not in text:
        text = replace_once(text, old_reason, new_reason, "CAP20 audit reason")
    return text


def patch_live(text: str) -> str:
    old_terminal = """    def _terminal_invalidated(self, rr: _ReferenceRuntime, close: float) -> bool:
        if rr.reference.reference_type == "RED":
            return close > rr.reference.high
        return close < rr.reference.low
"""
    new_terminal = """    def _terminal_invalidated(self, rr: _ReferenceRuntime, close: float) -> bool:
        # Canonical Family-B structural terminal is adverse MIDPOINT close.
        if rr.reference.reference_type == "RED":
            return close > rr.reference.midpoint
        return close < rr.reference.midpoint
"""
    if new_terminal not in text:
        text = replace_once(text, old_terminal, new_terminal, "midpoint structural terminal")

    if "def _favorable_points(" not in text:
        anchor = """    def _directional_points(self, rr: _ReferenceRuntime, close: float) -> float:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("directional points requested before entry")
        return self.engine.manager.directional_points(
            lifecycle.direction,
            lifecycle.entry_underlying_close,
            close,
        )

"""
        addition = anchor + """    def _favorable_points(self, rr: _ReferenceRuntime, underlying) -> float:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("favorable points requested before entry")
        favorable_price = (
            self._float(underlying, "high")
            if lifecycle.direction == "BULLISH"
            else self._float(underlying, "low")
        )
        return self.engine.manager.directional_points(
            lifecycle.direction,
            lifecycle.entry_underlying_close,
            favorable_price,
        )

"""
        text = replace_once(text, anchor, addition, "favorable excursion helper")

    text = text.replace("    running_close_mfe: float = 0.0\n", "    running_mfe: float = 0.0\n", 1)
    text = text.replace("rr.running_close_mfe", "rr.running_mfe")

    old_sig = """    def _process_management(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation | None,
    ) -> bool:
"""
    new_sig = """    def _process_management(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation | None,
        underlying,
    ) -> bool:
"""
    if new_sig not in text:
        text = replace_once(text, old_sig, new_sig, "management underlying signature")

    old_block = """        if self._terminal_invalidated(rr, obs.close):
            self._close_terminal(rr, obs, "ORIGINAL_FULL_RANGE_INVALIDATION")
            return True

        points = self._directional_points(rr, obs.close)
        rr.running_mfe = max(rr.running_mfe, points)

        # +20 proof: first exact completed 1m close at or above +20.
        if lifecycle.plus20_timestamp is None and points >= 20.0:
            self.engine.mark_plus20(rr.runtime, obs)
            rr.plus20_points = points
"""
    new_block = """        if self._terminal_invalidated(rr, obs.close):
            self._close_terminal(rr, obs, "MIDPOINT_INVALIDATION")
            return True

        points = self._directional_points(rr, obs.close)
        favorable_points = self._favorable_points(rr, underlying)
        rr.running_mfe = max(rr.running_mfe, favorable_points)

        # Canonical +20 proof is favorable intrabar excursion:
        # BULLISH uses high, BEARISH uses low.
        if lifecycle.plus20_timestamp is None and favorable_points >= 20.0:
            self.engine.mark_plus20(rr.runtime, obs)
            rr.plus20_points = 20.0
"""
    if new_block not in text:
        text = replace_once(text, old_block, new_block, "canonical terminal/proof/MFE")

    old_call = """                terminal_this_minute = self._process_management(
                    active_rr, obs, prev_obs
                )
"""
    new_call = """                terminal_this_minute = self._process_management(
                    active_rr, obs, prev_obs, underlying
                )
"""
    if new_call not in text:
        text = replace_once(text, old_call, new_call, "management call")

    text = text.replace("                    rr.running_close_mfe = 0.0\n", "                    rr.running_mfe = 0.0\n", 1)
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    paths = [STRUCTURE, SHADOW, RUNTIME, LIVE]
    for p in paths:
        if not p.exists():
            raise SystemExit(f"STOP: missing {p}")

    old = {p: p.read_text() for p in paths}
    new = {
        STRUCTURE: patch_structure(old[STRUCTURE]),
        SHADOW: patch_shadow(old[SHADOW]),
        RUNTIME: patch_runtime(old[RUNTIME]),
        LIVE: patch_live(old[LIVE]),
    }

    print("MIDPOINT M3B.1 CANONICAL PARITY PATCH")
    print("=" * 92)
    for p in paths:
        print(f"{p.relative_to(ROOT)} changed={new[p] != old[p]}")
    print("Safety unchanged: observation-only, execution off, quantity None.")

    if not args.apply:
        print("DRY RUN ONLY.")
        return

    for p in paths:
        backup = p.with_suffix(p.suffix + ".pre-midpoint-m3b1.bak")
        if not backup.exists():
            shutil.copy2(p, backup)
        p.write_text(new[p])

    print("APPLIED")
    print("MIDPOINT_SHADOW_ENABLED is not changed by this patch.")


if __name__ == "__main__":
    main()

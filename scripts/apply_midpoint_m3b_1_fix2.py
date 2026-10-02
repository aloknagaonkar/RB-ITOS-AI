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

def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"STOP: expected exactly one {label} anchor, found {n}")
    return text.replace(old, new, 1)

def patch_structure(text):
    old = '''def structure_still_valid(reference: ReferenceStructure, close: float) -> bool:
    # Frozen Family-B lifecycle constraint:
    # while waiting for delayed confirmation the same directional structure
    # must remain valid. For the first shadow implementation we preserve the
    # original full-range opposite-side invalidation.
    if reference.reference_type == "RED":
        return close <= reference.high
    return close >= reference.low
'''
    new = '''def structure_still_valid(reference: ReferenceStructure, close: float) -> bool:
    # Canonical Family-B delayed-confirmation lifecycle.
    if reference.reference_type == "RED":
        return close <= reference.midpoint
    return close >= reference.midpoint
'''
    return text if new in text else replace_once(text, old, new, "structure_still_valid")

def patch_shadow(text):
    old_fields = '''    reentry_timestamp: Optional[datetime] = None
    reentry_count: int = 0

    state: MidpointShadowState = MidpointShadowState.ACTIVE
'''
    new_fields = '''    reentry_timestamp: Optional[datetime] = None
    reentry_count: int = 0

    cap20_rebreak_evaluated: bool = False

    state: MidpointShadowState = MidpointShadowState.ACTIVE
'''
    if "cap20_rebreak_evaluated: bool = False" not in text:
        text = replace_once(text, old_fields, new_fields, "cap20 field")

    old_method = '''        if timestamp < rt.recovery_timestamp + timedelta(minutes=10):
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
'''
    new_method = '''        if timestamp < rt.recovery_timestamp + timedelta(minutes=10):
            return None

        if rt.cap20_rebreak_evaluated:
            return None

        # Canonical CAP20: first eligible post-recovery rebreak only.
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
'''
    return text if new_method in text else replace_once(text, old_method, new_method, "maybe_cap20_rescue")

def patch_runtime(text):
    old = '''        before = rt.state.value

        sig = self.manager.maybe_cap20_rescue(
'''
    new = '''        before = rt.state.value
        rebreak_evaluated_before = rt.cap20_rebreak_evaluated

        sig = self.manager.maybe_cap20_rescue(
'''
    if "rebreak_evaluated_before = rt.cap20_rebreak_evaluated" not in text:
        text = replace_once(text, old, new, "cap20 audit pre-state")

    old_reason = '''                result="NO_ACTION",
                reason="CAP20_CONDITIONS_NOT_ALL_MET",
'''
    new_reason = '''                result="NO_ACTION",
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
'''
    if "CAP20_FIRST_REBREAK_ABOVE_20_NO_RESCUE" not in text:
        text = replace_once(text, old_reason, new_reason, "cap20 audit reason")
    return text

def patch_live(text):
    old_terminal = '''    def _terminal_invalidated(self, rr: _ReferenceRuntime, close: float) -> bool:
        if rr.reference.reference_type == "RED":
            return close > rr.reference.high
        return close < rr.reference.low
'''
    new_terminal = '''    def _terminal_invalidated(self, rr: _ReferenceRuntime, close: float) -> bool:
        # Canonical Family-B terminal: adverse midpoint close.
        if rr.reference.reference_type == "RED":
            return close > rr.reference.midpoint
        return close < rr.reference.midpoint
'''
    if new_terminal not in text:
        text = replace_once(text, old_terminal, new_terminal, "terminal function")

    helper = '''    def _directional_points(self, rr: _ReferenceRuntime, close: float) -> float:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("directional points requested before entry")
        return self.engine.manager.directional_points(
            lifecycle.direction,
            lifecycle.entry_underlying_close,
            close,
        )
'''
    helper_new = helper + '''
    def _favorable_points(self, rr: _ReferenceRuntime, underlying) -> float:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("favorable points requested before entry")
        px = (
            self._float(underlying, "high")
            if lifecycle.direction == "BULLISH"
            else self._float(underlying, "low")
        )
        return self.engine.manager.directional_points(
            lifecycle.direction,
            lifecycle.entry_underlying_close,
            px,
        )
'''
    if "def _favorable_points(" not in text:
        text = replace_once(text, helper, helper_new, "favorable helper")

    old_sig = '''    def _process_management(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation | None,
    ) -> bool:
'''
    new_sig = '''    def _process_management(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation | None,
        underlying,
    ) -> bool:
'''
    if new_sig not in text:
        text = replace_once(text, old_sig, new_sig, "management signature")

    old_reason = '''        if self._terminal_invalidated(rr, obs.close):
            self._close_terminal(rr, obs, "ORIGINAL_FULL_RANGE_INVALIDATION")
            return True
'''
    new_reason = '''        if self._terminal_invalidated(rr, obs.close):
            self._close_terminal(rr, obs, "MIDPOINT_INVALIDATION")
            return True
'''
    if new_reason not in text:
        text = replace_once(text, old_reason, new_reason, "terminal reason")

    old_points = '''        points = self._directional_points(rr, obs.close)
        rr.running_close_mfe = max(rr.running_close_mfe, points)

        if lifecycle.plus20_timestamp is None and points >= 20.0:
            self.engine.mark_plus20(rr.runtime, obs)
            rr.plus20_points = points
'''
    new_points = '''        points = self._directional_points(rr, obs.close)
        favorable_points = self._favorable_points(rr, underlying)
        rr.running_close_mfe = max(rr.running_close_mfe, favorable_points)

        # Canonical +20 proof uses favorable 1m high/low excursion.
        if lifecycle.plus20_timestamp is None and favorable_points >= 20.0:
            self.engine.mark_plus20(rr.runtime, obs)
            rr.plus20_points = 20.0
'''
    if new_points not in text:
        text = replace_once(text, old_points, new_points, "proof/MFE block")

    old_call = '''                terminal_this_minute = self._process_management(
                    active_rr, obs, prev_obs
                )
'''
    new_call = '''                terminal_this_minute = self._process_management(
                    active_rr, obs, prev_obs, underlying
                )
'''
    if new_call not in text:
        text = replace_once(text, old_call, new_call, "management call")
    return text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

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

    print("MIDPOINT M3B.1 FIX2 — CANONICAL PARITY PATCH")
    print("=" * 94)
    for p in paths:
        print(f"{p.relative_to(ROOT)} changed={new[p] != old[p]}")
    print("Safety unchanged; MIDPOINT_SHADOW_ENABLED untouched.")

    if not args.apply:
        print("DRY RUN ONLY.")
        return

    for p in paths:
        backup = p.with_suffix(p.suffix + ".pre-midpoint-m3b1-fix2.bak")
        if not backup.exists():
            shutil.copy2(p, backup)
        p.write_text(new[p])

    print("APPLIED")

if __name__ == "__main__":
    main()

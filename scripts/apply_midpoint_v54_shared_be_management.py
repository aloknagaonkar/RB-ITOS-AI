#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

FILES = {
    "models": Path("backend/market_lab/midpoint_strategy/models.py"),
    "config": Path("backend/market_lab/midpoint_strategy/config.py"),
    "shadow": Path("backend/market_lab/midpoint_strategy/family_b_shadow.py"),
    "runtime": Path("backend/market_lab/midpoint_strategy/runtime.py"),
}

def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"STOP: {label}: expected exactly one anchor, found {n}")
    return text.replace(old, new, 1)

def patch_models(s: str) -> str:
    return replace_once(
        s,
        '''class MidpointFamily(str, Enum):
    B = "B"
    C = "C"
''',
        '''class MidpointFamily(str, Enum):
    B = "B"
    E = "E"
    C = "C"
''',
        "models MidpointFamily",
    )

def patch_config(s: str) -> str:
    s = replace_once(
        s,
        '''    family_b_enabled: bool = True
    family_c_enabled: bool = False
''',
        '''    family_b_enabled: bool = True
    # V54 introduces Family E management parity but keeps E disabled live.
    family_e_enabled: bool = False
    family_c_enabled: bool = False
''',
        "config family flags",
    )
    s = replace_once(
        s,
        '''        if self.family_c_enabled or self.family_d_enabled or self.pm_e_enabled:
            raise ValueError("Phase M1 enables Family B only")
''',
        '''        if self.family_e_enabled:
            raise ValueError("V54 keeps Family E disabled in live shadow until explicit later enablement")
        if self.family_c_enabled or self.family_d_enabled or self.pm_e_enabled:
            raise ValueError("Phase M1 enables Family B only")
''',
        "config safety assertion",
    )
    return s

def patch_shadow(s: str) -> str:
    s = replace_once(
        s,
        '''    direction: str
    entry_timestamp: datetime
    entry_underlying_close: float
''',
        '''    direction: str
    entry_timestamp: datetime
    entry_underlying_close: float
    # V54: management is shared by B and E. Default keeps all existing B callers unchanged.
    family: MidpointFamily = MidpointFamily.B
''',
        "shadow runtime family",
    )
    count = s.count("family=MidpointFamily.B")
    if count < 5:
        raise SystemExit(f"STOP: shadow manager family anchors unexpectedly low: {count}")
    s = s.replace("family=MidpointFamily.B", "family=rt.family")
    return s

def patch_runtime(s: str) -> str:
    s = replace_once(
        s,
        '''from .models import MidpointShadowState
''',
        '''from .models import MidpointFamily, MidpointShadowState
''',
        "runtime model import",
    )
    s = replace_once(
        s,
        '''class MidpointFamilyBRuntime:
    reference: ReferenceStructure
    watch: Optional[FamilyBWatch] = None
    lifecycle: Optional[FamilyBShadowRuntime] = None
    rescue_directional_vwap: Optional[float] = None
''',
        '''class MidpointFamilyBRuntime:
    reference: ReferenceStructure
    watch: Optional[FamilyBWatch] = None
    lifecycle: Optional[FamilyBShadowRuntime] = None
    rescue_directional_vwap: Optional[float] = None
    # Structural-event owner. Existing callers remain B by default.
    family: MidpointFamily = MidpointFamily.B
''',
        "runtime family field",
    )
    s = replace_once(
        s,
        '''                family="B",
                event_timestamp=timestamp,
''',
        '''                family=runtime.family.value,
                event_timestamp=timestamp,
''',
        "runtime deterministic event family",
    )
    s = replace_once(
        s,
        '''            family="B",
            event_timestamp=timestamp,
''',
        '''            family=runtime.family.value,
            event_timestamp=timestamp,
''',
        "runtime audit family",
    )
    s = replace_once(
        s,
        '''            runtime.lifecycle = FamilyBShadowRuntime(
                direction=runtime.reference.direction,
                entry_timestamp=datetime.fromisoformat(obs.timestamp),
                entry_underlying_close=obs.close,
                state=MidpointShadowState.ACTIVE,
            )
''',
        '''            runtime.family = MidpointFamily.B
            runtime.lifecycle = FamilyBShadowRuntime(
                direction=runtime.reference.direction,
                entry_timestamp=datetime.fromisoformat(obs.timestamp),
                entry_underlying_close=obs.close,
                family=MidpointFamily.B,
                state=MidpointShadowState.ACTIVE,
            )
''',
        "runtime B lifecycle creation",
    )

    anchor = '''        return d.result

    def mark_plus20(
'''
    new = '''        return d.result

    def start_e_entry(
        self,
        runtime: MidpointFamilyBRuntime,
        boundary_obs: FamilyBObservation,
    ) -> None:
        # Frozen Family-E entry at the structural boundary.
        # All post-entry management methods are exactly the same methods used by B.
        if runtime.lifecycle is not None:
            raise ValueError("lifecycle already active")

        if runtime.reference.direction == "BEARISH":
            mature = boundary_obs.raw_futures_vwap_diff < -self.detector.VWAP_THRESHOLD
        else:
            mature = boundary_obs.raw_futures_vwap_diff > self.detector.VWAP_THRESHOLD

        if not mature:
            raise ValueError("Family E requires mature directional VWAP at boundary")

        runtime.family = MidpointFamily.E
        runtime.watch = None
        runtime.lifecycle = FamilyBShadowRuntime(
            direction=runtime.reference.direction,
            entry_timestamp=datetime.fromisoformat(boundary_obs.timestamp),
            entry_underlying_close=boundary_obs.close,
            family=MidpointFamily.E,
            state=MidpointShadowState.ACTIVE,
        )
        self._audit(
            runtime=runtime,
            timestamp=boundary_obs.timestamp,
            event_type="E_ENTRY",
            direction=runtime.reference.direction,
            result="SHADOW_ENTRY",
            reason="MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY",
            state_before="BOUNDARY_CLASSIFIED_E",
            state_after="ACTIVE",
            observation=boundary_obs,
            directional_points=0.0,
            evidence={
                "action_intent": "SHADOW_ENTRY",
                "order_sent": False,
                "candidate_a_at_boundary": False,
                "raw_futures_vwap_diff": boundary_obs.raw_futures_vwap_diff,
            },
        )

    def mark_plus20(
'''
    s = replace_once(s, anchor, new, "runtime E entry insertion")
    return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    funcs = {
        "models": patch_models,
        "config": patch_config,
        "shadow": patch_shadow,
        "runtime": patch_runtime,
    }

    changed = {}
    for key, path in FILES.items():
        if not path.exists():
            raise SystemExit(f"STOP: missing {path}")
        before = path.read_text()
        after = funcs[key](before)
        changed[str(path)] = before != after
        if args.apply:
            backup = path.with_suffix(path.suffix + ".pre-v54.bak")
            if not backup.exists():
                backup.write_text(before)
            path.write_text(after)

    print("V54 patch validation:")
    for path, ok in changed.items():
        print(f"  {path}: changed={ok}")
    print("mode:", "APPLIED" if args.apply else "DRY_RUN")
    print("Family E remains live-disabled by config.")
    print("No execution/order safety setting is changed.")

if __name__ == "__main__":
    main()

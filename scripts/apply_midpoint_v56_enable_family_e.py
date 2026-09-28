#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

CONFIG = Path("backend/market_lab/midpoint_strategy/config.py")
LIVE = Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"STOP: {label}: expected exactly one anchor, found {n}")
    return text.replace(old, new, 1)


def patch_config(s: str) -> str:
    old = (
        "    # V54 introduces Family E management parity but keeps E disabled live.\n"
        "    family_e_enabled: bool = False\n"
    )
    new = (
        "    # V56: Family E is enabled for observation-only live shadow.\n"
        "    family_e_enabled: bool = True\n"
    )
    s = replace_once(s, old, new, "config family_e flag")

    old = (
        "        if self.family_e_enabled:\n"
        "            raise ValueError(\"V54 keeps Family E disabled in live shadow until explicit later enablement\")\n"
        "        if self.family_c_enabled or self.family_d_enabled or self.pm_e_enabled:\n"
        "            raise ValueError(\"Phase M1 enables Family B only\")\n"
    )
    new = (
        "        if self.family_c_enabled or self.family_d_enabled or self.pm_e_enabled:\n"
        "            raise ValueError(\"V56 live shadow enables only Family B + Family E\")\n"
    )
    s = replace_once(s, old, new, "config family safety")
    return s


def patch_live(s: str) -> str:
    old = (
        "from .config import MidpointShadowConfig\n"
        "from .family_b_detector import FamilyBObservation\n"
        "from .models import MidpointShadowState\n"
    )
    new = (
        "from .boundary_classifier import MidpointBoundaryClassifierV55, OTHER_FRESH_A\n"
        "from .config import MidpointShadowConfig\n"
        "from .family_b_detector import FamilyBObservation\n"
        "from .models import MidpointFamily, MidpointShadowState\n"
    )
    s = replace_once(s, old, new, "live imports")

    old = (
        "        self.engine = AuditableFamilyBEngine(\n"
        "            journal_path=audit_path,\n"
        "            config=self.config,\n"
        "        )\n"
        "        self.state: _SessionState | None = None\n"
    )
    new = (
        "        self.engine = AuditableFamilyBEngine(\n"
        "            journal_path=audit_path,\n"
        "            config=self.config,\n"
        "        )\n"
        "        self.boundary_classifier = MidpointBoundaryClassifierV55()\n"
        "        self.state: _SessionState | None = None\n"
    )
    s = replace_once(s, old, new, "classifier init")

    old = (
        "                self.engine._audit(\n"
        "                    runtime=rr.runtime,\n"
        "                    timestamp=obs.timestamp,\n"
        "                    event_type=\"BOUNDARY_BREAK\",\n"
        "                    direction=rr.reference.direction,\n"
        "                    result=\"CONFIRMED_CLOSE\",\n"
        "                    reason=\"ONE_MINUTE_CLOSE_BEYOND_ORIGINAL_BOUNDARY\",\n"
        "                    observation=obs,\n"
        "                )\n"
        "                self.engine.start_b_watch(\n"
        "                    rr.runtime,\n"
        "                    obs,\n"
        "                    self.state.observations,\n"
        "                )\n"
        "                continue\n"
    )

    new = (
        "                self.engine._audit(\n"
        "                    runtime=rr.runtime,\n"
        "                    timestamp=obs.timestamp,\n"
        "                    event_type=\"BOUNDARY_BREAK\",\n"
        "                    direction=rr.reference.direction,\n"
        "                    result=\"CONFIRMED_CLOSE\",\n"
        "                    reason=\"ONE_MINUTE_CLOSE_BEYOND_ORIGINAL_BOUNDARY\",\n"
        "                    observation=obs,\n"
        "                )\n"
        "\n"
        "                decision = self.boundary_classifier.classify(\n"
        "                    reference=rr.reference,\n"
        "                    boundary_observation=obs,\n"
        "                    history=self.state.observations,\n"
        "                )\n"
        "\n"
        "                if decision.owner == MidpointFamily.E.value:\n"
        "                    rr.runtime.family = MidpointFamily.E\n"
        "                else:\n"
        "                    rr.runtime.family = MidpointFamily.B\n"
        "\n"
        "                self.engine._audit(\n"
        "                    runtime=rr.runtime,\n"
        "                    timestamp=obs.timestamp,\n"
        "                    event_type=\"BOUNDARY_CLASSIFIED\",\n"
        "                    direction=rr.reference.direction,\n"
        "                    result=decision.owner,\n"
        "                    reason=decision.reason,\n"
        "                    observation=obs,\n"
        "                    evidence={\n"
        "                        \"family_selected\": decision.owner,\n"
        "                        \"candidate_a_at_boundary\": decision.candidate_a_at_boundary,\n"
        "                        \"prior_window_crossed_threshold\": decision.prior_window_crossed_threshold,\n"
        "                        \"raw_futures_vwap_diff\": decision.raw_futures_vwap_diff,\n"
        "                        \"directional_vwap_diff\": decision.directional_vwap_diff,\n"
        "                    },\n"
        "                )\n"
        "\n"
        "                if decision.owner == MidpointFamily.E.value:\n"
        "                    if not self.config.family_e_enabled:\n"
        "                        self.engine._audit(\n"
        "                            runtime=rr.runtime,\n"
        "                            timestamp=obs.timestamp,\n"
        "                            event_type=\"E_SELECTED_BUT_DISABLED\",\n"
        "                            direction=rr.reference.direction,\n"
        "                            result=\"NO_ENTRY\",\n"
        "                            reason=\"FAMILY_E_DISABLED\",\n"
        "                            observation=obs,\n"
        "                        )\n"
        "                        continue\n"
        "\n"
        "                    if another_active:\n"
        "                        self.engine._audit(\n"
        "                            runtime=rr.runtime,\n"
        "                            timestamp=obs.timestamp,\n"
        "                            event_type=\"E_ENTRY_BLOCKED\",\n"
        "                            direction=rr.reference.direction,\n"
        "                            result=\"NO_ENTRY\",\n"
        "                            reason=\"ANOTHER_REFERENCE_ACTIVE\",\n"
        "                            observation=obs,\n"
        "                        )\n"
        "                        continue\n"
        "\n"
        "                    self.engine.start_e_entry(rr.runtime, obs)\n"
        "                    self.state.active_reference_type = ref_type\n"
        "                    rr.running_close_mfe = 0.0\n"
        "                    continue\n"
        "\n"
        "                if decision.owner == MidpointFamily.B.value:\n"
        "                    self.engine.start_b_watch(\n"
        "                        rr.runtime,\n"
        "                        obs,\n"
        "                        self.state.observations,\n"
        "                    )\n"
        "                    continue\n"
        "\n"
        "                if decision.owner == OTHER_FRESH_A:\n"
        "                    self.engine._audit(\n"
        "                        runtime=rr.runtime,\n"
        "                        timestamp=obs.timestamp,\n"
        "                        event_type=\"BOUNDARY_OWNER_OTHER\",\n"
        "                        direction=rr.reference.direction,\n"
        "                        result=\"NO_B_OR_E_ENTRY\",\n"
        "                        reason=\"FRESH_CANDIDATE_A_AT_BOUNDARY\",\n"
        "                        observation=obs,\n"
        "                    )\n"
        "                    continue\n"
        "\n"
        "                raise AssertionError(f\"unsupported boundary owner: {decision.owner}\")\n"
    )
    s = replace_once(s, old, new, "boundary selection wiring")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    for path, fn in ((CONFIG, patch_config), (LIVE, patch_live)):
        if not path.exists():
            raise SystemExit(f"STOP: missing {path}")
        before = path.read_text()
        after = fn(before)
        print(f"{path}: changed={before != after}")
        if args.apply:
            backup = path.with_suffix(path.suffix + ".pre-v56.bak")
            if not backup.exists():
                backup.write_text(before)
            path.write_text(after)

    print("mode:", "APPLIED" if args.apply else "DRY_RUN")
    print("family_e_enabled=True")
    print("observation_only=True")
    print("execution_enabled=False")
    print("paper_order_enabled=False")
    print("quantity=None")


if __name__ == "__main__":
    main()

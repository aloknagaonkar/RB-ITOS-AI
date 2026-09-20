from __future__ import annotations

from pathlib import Path

TARGET = Path("backend/market_lab/nifty_oi_movement_magnitude_attribution_v1.py")

OLD_FIELD = r'''def _field(row: dict[str, Any], stem: str, horizon: int) -> float | None:
    candidates = [
        f"{stem}_{horizon}m",
        f"{stem}_{horizon}",
    ]
    for key in candidates:
        if key in row:
            value = _f(row.get(key))
            if value is not None:
                return value
    return None
'''

NEW_FIELD = r'''def _field(row: dict[str, Any], stem: str, horizon: int) -> float | None:
    # Prefer explicit flat fields when present.
    candidates = [
        f"{stem}_{horizon}m",
        f"{stem}_{horizon}",
    ]
    for key in candidates:
        if key in row:
            value = _f(row.get(key))
            if value is not None:
                return value

    # Canonical enriched schema stores the causal 5m/10m/15m values under
    # moving_horizons["5m"|"10m"|"15m"].
    horizons = row.get("moving_horizons")
    if isinstance(horizons, dict):
        h = horizons.get(f"{horizon}m")
        if isinstance(h, dict):
            status = str(h.get("status") or "").upper()
            if status and status != "AVAILABLE":
                return None

            nested_key = {
                "ce_delta": "ce_delta",
                "pe_delta": "pe_delta",
                "imbalance": "imbalance",
                "pcr_change": "pcr_change",
            }.get(stem)

            if nested_key:
                value = _f(h.get(nested_key))
                if value is not None:
                    return value

    # Backward-compatible 5m aliases used by enrichment UI/API.
    if horizon == 5:
        alias = {
            "ce_delta": "m_ce_delta",
            "pe_delta": "m_pe_delta",
            "pcr_change": "m_pcr_change",
        }.get(stem)
        if alias:
            value = _f(row.get(alias))
            if value is not None:
                return value

        if stem == "imbalance":
            ce = _f(row.get("m_ce_delta"))
            pe = _f(row.get("m_pe_delta"))
            if ce is not None and pe is not None:
                return pe - ce

    return None
'''

OLD_PCR = r'''                "pcr_current": _f(
                    row.get("pcr_current")
                    if "pcr_current" in row
                    else row.get("moving_pcr")
                ),
'''

NEW_PCR = r'''                "pcr_current": _f(
                    row.get("pcr_current")
                    if "pcr_current" in row
                    else (
                        row.get("moving_pcr")
                        if "moving_pcr" in row
                        else row.get("m_pcr")
                    )
                ),
'''

OLD_RUN = r'''    source_rows = load_checkpoints(enrichment_root, canonical_coverage)
    checkpoints = build_checkpoint_dataset(source_rows)
    attribution = analyze(checkpoints)

    session_dates = sorted({r["session_date"] for r in checkpoints})
'''

NEW_RUN = r'''    source_rows = load_checkpoints(enrichment_root, canonical_coverage)
    checkpoints = build_checkpoint_dataset(source_rows)

    oi_coverage = {
        f"{lb}m": sum(
            1 for r in checkpoints
            if r.get(f"imbalance_{lb}m") is not None
        )
        for lb in OI_LOOKBACKS
    }
    if oi_coverage["5m"] == 0:
        raise ValueError(
            "No 5m OI imbalance values were extracted from enriched rows. "
            "Expected canonical enriched moving_horizons schema."
        )

    attribution = analyze(checkpoints)

    session_dates = sorted({r["session_date"] for r in checkpoints})
'''

OLD_RESULT = r'''        "checkpoint_count": len(checkpoints),
        "forward_horizons_minutes": list(FORWARD_HORIZONS),
'''

NEW_RESULT = r'''        "checkpoint_count": len(checkpoints),
        "oi_coverage_by_lookback": oi_coverage,
        "forward_horizons_minutes": list(FORWARD_HORIZONS),
'''

OLD_PRINT = r'''        "checkpoint_count": result["checkpoint_count"],
        "movement_definition": result["movement_definition"],
'''

NEW_PRINT = r'''        "checkpoint_count": result["checkpoint_count"],
        "oi_coverage_by_lookback": result["oi_coverage_by_lookback"],
        "movement_definition": result["movement_definition"],
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already patched")
        return text
    if old not in text:
        raise SystemExit(f"{label}: expected source block not found; refusing unsafe patch")
    print(f"{label}: patched")
    return text.replace(old, new, 1)


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"missing target: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    text = replace_once(text, OLD_FIELD, NEW_FIELD, "_field nested moving_horizons extraction")
    text = replace_once(text, OLD_PCR, NEW_PCR, "m_pcr current PCR alias")
    text = replace_once(text, OLD_RUN, NEW_RUN, "OI extraction coverage gate")
    text = replace_once(text, OLD_RESULT, NEW_RESULT, "OI coverage report field")
    text = replace_once(text, OLD_PRINT, NEW_PRINT, "OI coverage console field")

    TARGET.write_text(text, encoding="utf-8")
    print(f"Patched: {TARGET}")


if __name__ == "__main__":
    main()

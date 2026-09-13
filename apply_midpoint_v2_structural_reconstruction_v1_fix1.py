from pathlib import Path

p = Path("backend/market_lab/midpoint_v2_structural_reconstruction_v1.py")
text = p.read_text(encoding="utf-8")

old = '''        result = route_v2_extension(
            t3_state=str(ev["t3_state"]),
            direction=direction,
            boundary=boundary,
            midpoint=midpoint,
            closes_after_t3=closes,
            config=config,
        )

        chained_reclaim = None
        if (
            ev["t3_state"] == STATE_WAIT_BASE
            and result.final_state == STATE_RECLAIM_WATCH
        ):
            start = (result.confirmation_bar_index or 0)
            remaining = closes[start:]
            chained_reclaim = evaluate_reclaim_watch(
                original_direction=direction,
                boundary=boundary,
                midpoint=midpoint,
                closes_after_t3=remaining,
                config=config,
            )
            if chained_reclaim.entry_arm == ARM_RECLAIM:
                result = chained_reclaim

        rows.append(
            {
                **ev,
                "reference_colour": src.get("reference_colour"),
                "reference_high": src.get("reference_high"),
                "reference_low": src.get("reference_low"),
                "reference_midpoint": src.get("reference_midpoint"),
                "boundary": boundary,
                "post_t3_close_count": len(closes),
                "post_t3_closes": closes,
                "v2_result": result.to_dict(),
                "chained_reclaim_result": (
                    chained_reclaim.to_dict() if chained_reclaim else None
                ),
            }
        )
'''

new = '''        result = route_v2_extension(
            t3_state=str(ev["t3_state"]),
            direction=direction,
            boundary=boundary,
            midpoint=midpoint,
            closes_after_t3=closes,
            config=config,
        )

        pre_chain_result = result
        chained_reclaim = None
        chained_reclaim_start_bar_index = None
        absolute_confirmation_bar_index = result.confirmation_bar_index

        if (
            ev["t3_state"] == STATE_WAIT_BASE
            and result.final_state == STATE_RECLAIM_WATCH
        ):
            start = result.confirmation_bar_index or 0
            chained_reclaim_start_bar_index = start
            remaining = closes[start:]
            chained_reclaim = evaluate_reclaim_watch(
                original_direction=direction,
                boundary=boundary,
                midpoint=midpoint,
                closes_after_t3=remaining,
                config=config,
            )
            if chained_reclaim.entry_arm == ARM_RECLAIM:
                result = chained_reclaim
                if chained_reclaim.confirmation_bar_index is None:
                    raise ValueError(
                        "confirmed chained reclaim missing confirmation_bar_index"
                    )
                absolute_confirmation_bar_index = (
                    start + chained_reclaim.confirmation_bar_index
                )

        confirmation_timestamp = None
        if result.entry_arm in {ARM_BASE, ARM_RECLAIM}:
            if absolute_confirmation_bar_index is None:
                raise ValueError(
                    "V2 entry arm missing absolute confirmation bar index"
                )
            confirmation_timestamp = (
                parse_dt(str(ev["t3_timestamp"]))
                + timedelta(minutes=absolute_confirmation_bar_index + 1)
            ).isoformat()
        elif result.entry_arm == ARM_IMMEDIATE:
            confirmation_timestamp = str(ev["t3_timestamp"])

        rows.append(
            {
                **ev,
                "reference_colour": src.get("reference_colour"),
                "reference_high": src.get("reference_high"),
                "reference_low": src.get("reference_low"),
                "reference_midpoint": src.get("reference_midpoint"),
                "boundary": boundary,
                "post_t3_close_count": len(closes),
                "post_t3_closes": closes,
                "pre_chain_result": pre_chain_result.to_dict(),
                "chained_reclaim_start_bar_index": chained_reclaim_start_bar_index,
                "absolute_confirmation_bar_index": absolute_confirmation_bar_index,
                "confirmation_timestamp": confirmation_timestamp,
                "v2_result": result.to_dict(),
                "chained_reclaim_result": (
                    chained_reclaim.to_dict() if chained_reclaim else None
                ),
            }
        )
'''

if old not in text:
    raise SystemExit(
        "Expected structural reconstruction block not found. "
        "Do not patch blindly; inspect the current file."
    )

text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")
print("Patched:", p)
print("Added explicit absolute confirmation timing fields.")

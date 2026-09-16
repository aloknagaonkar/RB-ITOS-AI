from pathlib import Path

TARGET = Path("backend/market_lab/historical_paper_replay_date_v1.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected exactly one match, found {count}. "
            "Refusing to modify file."
        )
    return text.replace(old, new, 1)


def main():
    text = TARGET.read_text()

    if "option_oi_index=None" in text and "load_option_oi_index(" in text:
        print("P3H.5.2.2 integration already present; no changes made.")
        return

    text = replace_once(
        text,
        '''def build_historical_oi_features(
    session: PositioningSession,
) -> list[OICheckpointFeature]:''',
        '''def build_historical_oi_features(
    session: PositioningSession,
    *,
    option_oi_index=None,
) -> list[OICheckpointFeature]:
    if option_oi_index is not None:
        from .fixed_strike_oi_fallback_v1 import (
            select_exact_strikes_with_oi_fallback,
        )''',
        "function signature",
    )

    text = replace_once(
        text,
        '''        current_fixed = _select_exact_strikes(current_rows, fixed_strikes)
        ce_fixed, pe_fixed = _sum_oi(current_fixed)''',
        '''        if option_oi_index is None:
            current_fixed = _select_exact_strikes(current_rows, fixed_strikes)
        else:
            current_fixed = select_exact_strikes_with_oi_fallback(
                current_rows,
                fixed_strikes,
                timestamp=ts,
                option_oi_index=option_oi_index,
            )
        ce_fixed, pe_fixed = _sum_oi(current_fixed)''',
        "current fixed strikes",
    )

    text = replace_once(
        text,
        '''        previous_fixed = _select_exact_strikes(previous_rows, fixed_strikes)
        ce_fixed_prev, pe_fixed_prev = _sum_oi(previous_fixed)''',
        '''        if option_oi_index is None:
            previous_fixed = _select_exact_strikes(previous_rows, fixed_strikes)
        else:
            previous_fixed = select_exact_strikes_with_oi_fallback(
                previous_rows,
                fixed_strikes,
                timestamp=previous_ts,
                option_oi_index=option_oi_index,
            )
        ce_fixed_prev, pe_fixed_prev = _sum_oi(previous_fixed)''',
        "previous fixed strikes",
    )

    text = replace_once(
        text,
        '''    features = build_historical_oi_features(positioning)''',
        '''    from .fixed_strike_oi_fallback_v1 import load_option_oi_index

    _option_oi_source, option_oi_index = load_option_oi_index(
        session_date,
        data_root=data_root,
    )
    features = build_historical_oi_features(
        positioning,
        option_oi_index=option_oi_index,
    )''',
        "replay integration",
    )

    TARGET.write_text(text)
    print(f"Applied P3H.5.2.2 integration to {TARGET}")


if __name__ == "__main__":
    main()

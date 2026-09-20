from market_lab.nifty_oi_movement_magnitude_attribution_v1 import (
    _field,
    build_checkpoint_dataset,
)


def enriched_row(ts, spot, h5, h10, h15):
    return {
        "session_date": "2026-08-25",
        "timestamp": ts,
        "spot": spot,
        "moving_atm": 24200.0,
        "m_pcr": h5["current_pcr"],
        "m_ce_delta": h5["ce_delta"],
        "m_pe_delta": h5["pe_delta"],
        "m_pcr_change": h5["pcr_change"],
        "moving_horizons": {
            "5m": {"status": "AVAILABLE", **h5},
            "10m": {"status": "AVAILABLE", **h10},
            "15m": {"status": "AVAILABLE", **h15},
        },
    }


def H(ce, pe, pcr=1.0, prior=0.9):
    return {
        "ce_delta": float(ce),
        "pe_delta": float(pe),
        "imbalance": float(pe - ce),
        "current_pcr": float(pcr),
        "prior_pcr": float(prior),
        "pcr_change": float(pcr - prior),
    }


def test_extracts_nested_canonical_enriched_horizons():
    r = enriched_row(
        "2026-08-25T10:00:00+05:30",
        24200.0,
        H(10, 30, 1.1, 1.0),
        H(20, 55, 1.2, 1.0),
        H(25, 70, 1.3, 1.0),
    )

    assert _field(r, "ce_delta", 5) == 10.0
    assert _field(r, "pe_delta", 5) == 30.0
    assert _field(r, "imbalance", 5) == 20.0
    assert abs(_field(r, "pcr_change", 5) - 0.1) < 1e-12

    assert _field(r, "imbalance", 10) == 35.0
    assert _field(r, "imbalance", 15) == 45.0


def test_build_checkpoint_dataset_populates_nested_oi_fields():
    rows = [
        enriched_row(
            "2026-08-25T10:00:00+05:30",
            24200.0,
            H(10, 30),
            H(20, 50),
            H(30, 70),
        ),
        enriched_row(
            "2026-08-25T10:05:00+05:30",
            24215.0,
            H(12, 32),
            H(22, 52),
            H(32, 72),
        ),
        enriched_row(
            "2026-08-25T10:10:00+05:30",
            24225.0,
            H(13, 33),
            H(23, 53),
            H(33, 73),
        ),
        enriched_row(
            "2026-08-25T10:15:00+05:30",
            24235.0,
            H(14, 34),
            H(24, 54),
            H(34, 74),
        ),
    ]

    out = build_checkpoint_dataset(rows)
    first = out[0]

    assert first["imbalance_5m"] == 20.0
    assert first["imbalance_10m"] == 30.0
    assert first["imbalance_15m"] == 40.0
    assert first["pcr_current"] == 1.0
    assert first["bull_excursion_15m"] == 35.0

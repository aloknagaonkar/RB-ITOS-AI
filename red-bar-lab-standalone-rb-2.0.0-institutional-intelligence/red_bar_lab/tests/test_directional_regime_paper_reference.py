from pathlib import Path
import json

from red_bar_lab.execution.directional_regime_reference import (
    DirectionalRegimeReferenceService,
)


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def service(tmp_path: Path):
    return DirectionalRegimeReferenceService(
        runs_root=tmp_path,
        maximum_age_minutes=30,
    )


def test_bullish_signal_aligns_with_bullish_bundle(tmp_path: Path):
    write_jsonl(
        tmp_path / "fresh_setup_bundles_v43" / "nifty.jsonl",
        [{
            "bundle_id": "B1",
            "instrument_key": "NSE_INDEX|Nifty 50",
            "direction": "BULLISH",
            "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
            "detected_at": "2026-08-14T10:00:00+00:00",
            "fresh_until": "2026-08-14T10:20:00+00:00",
        }],
    )
    result = service(tmp_path).evaluate(
        signal_direction="BULLISH",
        instrument_key="NSE_INDEX|Nifty 50",
        at_time="2026-08-14T10:05:00+00:00",
    )
    assert result.status == "ALIGNED"
    assert result.alignment_score == 100.0
    assert result.execution_allowed is False


def test_bearish_signal_conflicts_with_bullish_bundle(tmp_path: Path):
    write_jsonl(
        tmp_path / "fresh_setup_bundles_v43" / "nifty.jsonl",
        [{
            "bundle_id": "B1",
            "instrument_key": "NSE_INDEX|Nifty 50",
            "direction": "BULLISH",
            "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
            "detected_at": "2026-08-14T10:00:00",
            "fresh_until": "2026-08-14T10:20:00",
        }],
    )
    result = service(tmp_path).evaluate(
        signal_direction="BEARISH",
        instrument_key="NSE_INDEX|Nifty 50",
        at_time="2026-08-14T10:05:00",
    )
    assert result.status == "CONFLICT"
    assert result.alignment_score == 0.0


def test_expired_bundle_is_not_used(tmp_path: Path):
    write_jsonl(
        tmp_path / "fresh_setup_bundles_v43" / "nifty.jsonl",
        [{
            "bundle_id": "OLD",
            "instrument_key": "NSE_INDEX|Nifty 50",
            "direction": "BULLISH",
            "detected_at": "2026-08-14T09:15:00",
            "fresh_until": "2026-08-14T09:30:00",
        }],
    )
    result = service(tmp_path).evaluate(
        signal_direction="BULLISH",
        instrument_key="NSE_INDEX|Nifty 50",
        at_time="2026-08-14T10:05:00",
    )
    assert result.status == "UNAVAILABLE"


def test_sideways_regime_without_bundle_is_neutral(tmp_path: Path):
    write_jsonl(
        tmp_path / "stateful_regime_v43" / "nifty.jsonl",
        [{
            "instrument_key": "NSE_INDEX|Nifty 50",
            "regime": "SIDEWAYS",
            "evaluated_at": "2026-08-14T10:00:00",
        }],
    )
    result = service(tmp_path).evaluate(
        signal_direction="BULLISH",
        instrument_key="NSE_INDEX|Nifty 50",
        at_time="2026-08-14T10:05:00",
    )
    assert result.status == "NEUTRAL"
    assert result.alignment_score == 50.0

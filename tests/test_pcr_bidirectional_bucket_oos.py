import json
from pathlib import Path

from market_lab.pcr_bidirectional_bucket_oos import _is_monotonic, validate_fresh_oos


def test_monotonic_helper():
    assert _is_monotonic([10.0, 20.0, 20.0, 30.0], True)
    assert _is_monotonic([40.0, 30.0, 20.0, 10.0], False)
    assert not _is_monotonic([10.0, 30.0, 20.0, 40.0], True)


def test_rejects_unavailable_spec(tmp_path: Path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"status": "UNAVAILABLE"}), encoding="utf-8")
    evidence = tmp_path / "e.csv"
    evidence.write_text("x\n", encoding="utf-8")
    try:
        validate_fresh_oos(spec, evidence)
    except ValueError as exc:
        assert "not AVAILABLE" in str(exc)
    else:
        raise AssertionError("expected ValueError")

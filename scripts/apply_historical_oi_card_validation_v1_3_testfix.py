from pathlib import Path

src = Path("tests/test_historical_oi_card_validation_v1_3_testfix.py")
dst = Path("tests/test_historical_oi_card_validation_v1_2_scopefix.py")

if not src.exists():
    raise SystemExit("Safe-stop: V1.3 replacement test file not found.")

dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
print("Replaced brittle exact-spacing test with whitespace-tolerant V1.3 test.")

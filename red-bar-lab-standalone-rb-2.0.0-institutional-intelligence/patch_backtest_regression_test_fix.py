from pathlib import Path
import sys

TEST_FILE = Path("red_bar_lab/tests/test_backtest_target_index.py")

if not TEST_FILE.exists():
    print(f"ERROR: {TEST_FILE} not found.")
    print("Run this script from the project root.")
    sys.exit(1)

text = TEST_FILE.read_text(encoding="utf-8")

old = '''        mfe=22.0,
        mae=5.0,
        holding_minutes=30,
    )
'''

new = '''        mfe=22.0,
        mae=5.0,
        holding_minutes=30,
        session_mfe_points=25.0,
        session_mae_points=5.0,
        session_extreme_price=125.0,
        session_extreme_timestamp=datetime(
            2026, 8, 5, 10, 15, tzinfo=ist
        ),
        move_after_target_points=5.0,
        minutes_from_target_to_extreme=15,
        giveback_from_extreme_points=2.0,
    )
'''

count = text.count(old)
if count != 1:
    print(f"ERROR: Expected exactly one constructor block, found {count}.")
    sys.exit(2)

TEST_FILE.write_text(text.replace(old, new, 1), encoding="utf-8")

print("SUCCESS")
print(f"Updated: {TEST_FILE}")
print()
print("Now run:")
print("  python -m pytest red_bar_lab/tests/test_backtest_target_index.py -q")
print("  python -m pytest red_bar_lab/tests -q")

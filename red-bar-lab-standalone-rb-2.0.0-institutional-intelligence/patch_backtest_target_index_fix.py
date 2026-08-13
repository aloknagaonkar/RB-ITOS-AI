from pathlib import Path
import shutil
import sys

DB_FILE = Path("red_bar_lab/storage/database.py")
TEST_FILE = Path("red_bar_lab/tests/test_backtest_target_index.py")

if not DB_FILE.exists():
    print(f"ERROR: {DB_FILE} not found.")
    print("Run this script from the project root.")
    sys.exit(1)

text = DB_FILE.read_text(encoding="utf-8")
backup = DB_FILE.with_suffix(".py.before_backtest_index_fix")
shutil.copy2(DB_FILE, backup)

old = '''CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_trade_signal_target
ON paper_trade_outcomes(signal_id, target_points);
'''

new = '''-- Historical backtest exit models may legitimately share the same
-- numeric target_points for the same signal (for example FIXED_TARGET
-- 20pt and RISK_REWARD 1R when risk is 20 points). trade_id already
-- uniquely identifies signal + exit model + model parameter.
DROP INDEX IF EXISTS uq_paper_trade_signal_target;

CREATE INDEX IF NOT EXISTS idx_paper_trade_signal_target
ON paper_trade_outcomes(signal_id, target_points);
'''

count = text.count(old)
if count != 1:
    print(f"ERROR: Expected exactly one legacy unique-index block, found {count}.")
    print(f"Backup: {backup}")
    sys.exit(2)

text = text.replace(old, new, 1)
DB_FILE.write_text(text, encoding="utf-8")

test_content = '''from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.strategy.trade_models import (
    ExitModel,
    ExitReason,
    PaperTradeOutcome,
    TradeStatus,
)


def _outcome(*, trade_id, exit_model, model_parameter):
    ist = ZoneInfo("Asia/Kolkata")
    return PaperTradeOutcome(
        trade_id=trade_id,
        signal_id="SIG-SAME-TARGET",
        instrument_key="NIFTY",
        trading_date="2026-08-05",
        level_type="FIRST_CANDLE",
        direction="BULLISH",
        entry_timestamp=datetime(2026, 8, 5, 9, 30, tzinfo=ist),
        entry_price=100.0,
        stop_price=80.0,
        risk_points=20.0,
        exit_model=exit_model,
        model_parameter=model_parameter,
        target_points=20.0,
        target_price=120.0,
        exit_timestamp=datetime(2026, 8, 5, 10, 0, tzinfo=ist),
        exit_price=120.0,
        exit_reason=ExitReason.TARGET,
        status=TradeStatus.CLOSED,
        points=20.0,
        r_multiple=1.0,
        mfe=22.0,
        mae=5.0,
        holding_minutes=30,
    )


def test_same_signal_same_target_points_allowed_for_different_exit_models(tmp_path):
    database = RedBarDatabase(tmp_path / "same_target.db")
    database.initialize()

    fixed = _outcome(
        trade_id="TRD-FIXED-20",
        exit_model=ExitModel.FIXED_TARGET,
        model_parameter="20pt",
    )
    risk_reward = _outcome(
        trade_id="TRD-RR-1R",
        exit_model=ExitModel.RISK_REWARD,
        model_parameter="1R",
    )

    assert database.replace_paper_trade_outcomes(
        "NIFTY",
        "2026-08-05",
        (fixed, risk_reward),
    ) == 2

    rows = database.read_paper_trade_outcomes("NIFTY", "2026-08-05")
    assert len(rows) == 2
    assert {row["exit_model"] for row in rows} == {
        "FIXED_TARGET",
        "RISK_REWARD",
    }
'''

TEST_FILE.write_text(test_content, encoding="utf-8")

print("SUCCESS")
print(f"Updated : {DB_FILE}")
print(f"Backup  : {backup}")
print(f"Added   : {TEST_FILE}")
print()
print("Next:")
print("  python -m pytest red_bar_lab/tests/test_backtest_target_index.py -q")
print("  python -m pytest red_bar_lab/tests -q")
print()
print("Then rerun Bulk Historical Backtest.")

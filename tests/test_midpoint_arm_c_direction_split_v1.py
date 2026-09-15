from market_lab.midpoint_arm_c_direction_split_v1 import (
    metric_summary,
    summarize,
    validate_rows,
)


def row(direction, block, x):
    return {
        "direction": direction,
        "block": block,
        "net_returns_pct": {"1m": x, "3m": x, "5m": x, "10m": x, "15m": x},
    }


def test_metric_summary_profit_factor():
    s = metric_summary([2.0, -1.0, 3.0])
    assert s["count"] == 3
    assert s["positive_count"] == 2
    assert s["profit_factor"] == 5.0


def test_summarize_direction_counts():
    s = summarize([
        row("BULLISH", "TRAIN", 1.0),
        row("BEARISH", "OOS_A", -1.0),
    ])
    assert s["trade_count"] == 2
    assert s["direction_counts"]["BULLISH"] == 1
    assert s["direction_counts"]["BEARISH"] == 1


def test_forbidden_block_rejected():
    issues = validate_rows([row("BULLISH", "OOS_H", 1.0)])
    assert issues
    assert "forbidden block OOS_H" in issues[0]


def test_valid_development_blocks_pass():
    rows = [
        row("BULLISH", "TRAIN", 1.0),
        row("BEARISH", "OOS_A", -1.0),
        row("BEARISH", "OOS_D", 2.0),
    ]
    assert validate_rows(rows) == []

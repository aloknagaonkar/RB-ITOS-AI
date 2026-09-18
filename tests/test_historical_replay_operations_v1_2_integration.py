from pathlib import Path


def test_operations_worker_uses_v1_2_replay():
    text = Path(
        "backend/market_lab/historical_replay_operations_worker_v1.py"
    ).read_text(encoding="utf-8")

    assert "from .historical_replay_day_v1_2 import run_day" in text
    assert "from .historical_replay_day_v1_1 import run_day" not in text

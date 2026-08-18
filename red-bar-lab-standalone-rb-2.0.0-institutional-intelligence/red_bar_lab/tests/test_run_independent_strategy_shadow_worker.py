from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.run_independent_strategy_shadow_worker import (
    print_status,
    reference_levels_from_rows,
)


IST = ZoneInfo("Asia/Kolkata")


def test_reference_level_rows_reuse_existing_red_bar_shape():
    levels = reference_levels_from_rows(
        [
            {
                "level_type": "NEXT_RED_CANDLE",
                "level_value": 24125.5,
                "source_timestamp": "2026-08-18T09:20:00+05:30",
                "source_high": 24140.0,
                "source_low": 24110.0,
                "interval_minutes": 5,
            },
            {
                "level_type": "",
                "level_value": None,
                "source_timestamp": None,
            },
        ]
    )

    assert len(levels) == 1
    level = levels[0]
    assert level.level_type == "NEXT_RED_CANDLE"
    assert level.value == 24125.5
    assert level.source_timestamp == datetime(2026, 8, 18, 9, 20, tzinfo=IST)
    assert level.source_high == 24140.0
    assert level.source_low == 24110.0
    assert level.interval_minutes == 5


def test_print_status_reads_only_shadow_heartbeat(tmp_path: Path, capsys):
    settings = RedBarSettings(artifacts_root=tmp_path)
    status_path = (
        settings.runs_root
        / "independent_strategy_shadow_v1"
        / "NSE_INDEX_Nifty_50.status.json"
    )
    status_path.parent.mkdir(parents=True)
    status_path.write_text(
        json.dumps(
            {
                "status": "READY",
                "shadow_only": True,
                "production_persistence": False,
                "order_submitted": False,
            }
        ),
        encoding="utf-8",
    )

    code = print_status(settings, "NSE_INDEX|Nifty 50")
    output = capsys.readouterr().out

    assert code == 0
    assert '"status": "READY"' in output
    assert '"shadow_only": true' in output
    assert '"production_persistence": false' in output
    assert '"order_submitted": false' in output


def test_print_status_reports_missing_heartbeat(tmp_path: Path, capsys):
    settings = RedBarSettings(artifacts_root=tmp_path)
    code = print_status(settings, "NSE_INDEX|Nifty 50")
    output = capsys.readouterr().out

    assert code == 1
    assert "No shadow-worker status is available" in output

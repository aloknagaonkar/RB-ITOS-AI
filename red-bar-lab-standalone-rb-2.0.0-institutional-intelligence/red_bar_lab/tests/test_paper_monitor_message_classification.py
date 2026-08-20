from red_bar_lab.execution.paper_monitor import _partition_cycle_messages


def test_outside_entry_hours_is_warning_not_error():
    errors, warnings = _partition_cycle_messages(
        ("Automatic paper entry skipped outside entry market hours.",),
        (),
    )

    assert errors == []
    assert warnings == [
        "Automatic paper entry skipped outside entry market hours."
    ]


def test_real_report_and_reversal_failures_remain_errors():
    errors, warnings = _partition_cycle_messages(
        ("QUOTE_BATCH:RuntimeError:provider unavailable",),
        ("PAPER-1:close failed",),
    )

    assert errors == [
        "PAPER-1:close failed",
        "QUOTE_BATCH:RuntimeError:provider unavailable",
    ]
    assert warnings == []


def test_operational_warning_does_not_hide_other_errors():
    errors, warnings = _partition_cycle_messages(
        (
            "Automatic paper entry skipped outside entry market hours.",
            "DATABASE:OperationalError:locked",
        ),
        (),
    )

    assert errors == ["DATABASE:OperationalError:locked"]
    assert warnings == [
        "Automatic paper entry skipped outside entry market hours."
    ]

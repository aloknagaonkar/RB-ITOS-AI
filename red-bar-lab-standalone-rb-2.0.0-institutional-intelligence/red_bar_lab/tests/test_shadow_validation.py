from red_bar_lab.intelligence.validation import ShadowValidationService


class FakeValidationDatabase:
    def __init__(self):
        self.orders = [
            {
                "status": "CLOSED",
                "signal_id": "S1",
                "option_type": "CE",
                "realized_pnl": 500.0,
            },
            {
                "status": "CLOSED",
                "signal_id": "S2",
                "option_type": "CE",
                "realized_pnl": -300.0,
            },
            {
                "status": "CLOSED",
                "signal_id": "S3",
                "option_type": "PE",
                "realized_pnl": -200.0,
            },
            {
                "status": "CLOSED",
                "signal_id": "S4",
                "option_type": "PE",
                "realized_pnl": 400.0,
            },
        ]
        self.evaluations = [
            {
                "signal_id": "S4",
                "shadow_decision": "BUY CE",
                "shadow_confidence": 82,
                "evaluated_at": "2026-08-10T12:06:00+05:30",
                "modules": [
                    {
                        "module": "PCR",
                        "recommendation": "BUY CE",
                        "confidence": 82,
                    }
                ],
            },
            {
                "signal_id": "S3",
                "shadow_decision": "WAIT",
                "shadow_confidence": 70,
                "evaluated_at": "2026-08-10T12:04:00+05:30",
                "modules": [
                    {
                        "module": "PCR",
                        "recommendation": "WAIT",
                        "confidence": 70,
                    }
                ],
            },
            {
                "signal_id": "S2",
                "shadow_decision": "WAIT",
                "shadow_confidence": 75,
                "evaluated_at": "2026-08-10T12:02:00+05:30",
                "modules": [
                    {
                        "module": "PCR",
                        "recommendation": "WAIT",
                        "confidence": 75,
                    }
                ],
            },
            {
                "signal_id": "S1",
                "shadow_decision": "BUY CE",
                "shadow_confidence": 85,
                "evaluated_at": "2026-08-10T12:00:00+05:30",
                "modules": [
                    {
                        "module": "PCR",
                        "recommendation": "BUY CE",
                        "confidence": 85,
                    }
                ],
            },
        ]

    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER-STD"
        return list(self.orders)

    def read_shadow_intelligence_evaluations(
        self,
        *,
        signal_id=None,
        limit=200,
    ):
        rows = list(self.evaluations)
        if signal_id:
            rows = [
                row for row in rows
                if row.get("signal_id") == signal_id
            ]
        return rows[:limit]


def test_shadow_validation_is_conservative_and_resolves_wait_cases():
    result = ShadowValidationService(
        FakeValidationDatabase()
    ).evaluate()
    summary = result["summary"]

    assert summary.closed_trades == 4
    assert summary.current_wins == 2
    assert summary.current_losses == 2
    assert summary.current_win_rate == 50.0

    # S1 agreement + win -> correct
    # S2 WAIT + executed loss -> shadow correct
    # S3 WAIT + executed loss -> shadow correct
    # S4 opposite CE vs executed PE winner -> unresolved, not guessed.
    assert summary.shadow_correct == 3
    assert summary.shadow_wrong == 0
    assert summary.shadow_accuracy == 100.0
    assert summary.unresolved_disagreements == 1


def test_opposite_shadow_direction_remains_unresolved():
    db = FakeValidationDatabase()
    service = ShadowValidationService(db)
    assert service._resolve_shadow(
        actual_action="BUY PE",
        trade_result="WIN",
        shadow_action="BUY CE",
    ) == "UNRESOLVED"


def test_recommendation_stability_uses_latest_consecutive_decision():
    rows = [
        {
            "shadow_decision": "BUY PE",
            "evaluated_at": "2026-08-10T10:00:00+05:30",
        },
        {
            "shadow_decision": "BUY CE",
            "evaluated_at": "2026-08-10T10:05:00+05:30",
        },
        {
            "shadow_decision": "BUY CE",
            "evaluated_at": "2026-08-10T10:10:00+05:30",
        },
        {
            "shadow_decision": "BUY CE",
            "evaluated_at": "2026-08-10T10:20:00+05:30",
        },
    ]
    stability = ShadowValidationService.recommendation_stability(rows)
    assert stability["decision"] == "BUY CE"
    assert stability["samples"] == 3
    assert stability["minutes"] == 15.0


def test_module_promotion_requires_evidence_not_one_good_trade():
    result = ShadowValidationService(
        FakeValidationDatabase()
    ).evaluate()
    pcr = next(
        row for row in result["module_scoreboard"]
        if row["Module"] == "PCR"
    )
    assert pcr["Status"] == "OBSERVE"
    assert pcr["Promotion"] == "LEARNING"
    assert pcr["Execution Impact"] == "NONE"


def test_current_automation_still_does_not_import_validation_layer():
    from pathlib import Path
    path = (
        Path(__file__).resolve().parents[1]
        / "execution"
        / "automation.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "ShadowValidationService" not in text
    assert "intelligence.validation" not in text

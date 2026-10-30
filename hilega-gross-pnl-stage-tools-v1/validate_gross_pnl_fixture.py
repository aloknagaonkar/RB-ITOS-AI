"""Synthetic P&L arithmetic demonstration. No live account or production writes."""
import json
import test_gross_pnl as fixtures


def main():
    f=fixtures.GrossPnlTests();f.setUp()
    folder=f.f.a.path.parent
    try:
        result=f.preview(fee=f.fee(total=0))
        partial=f.preview(f.partial())
        assert result["gross_realized_paise"]==6175
        assert result["realized_net_pnl_paise"] is None
        assert result["account_aggregate_fees_applied_to_strategy"] is False
        assert partial["remaining_quantity"]==35
        assert partial["open_net_pnl_paise"] is None
    finally:
        f.doCleanups()
    assert not folder.exists()
    print(json.dumps(dict(
        status="GROSS_PNL_FIXTURE_PREVIEW_PASS",
        scope="SYNTHETIC_FIXTURE_ONLY",
        example_gross_realized_paise=6175,
        aggregate_fee_capture_assessed=True,
        aggregate_fees_applied_to_strategy=False,
        strategy_fees_paise=None,
        realized_net_pnl_paise=None,
        open_net_pnl_paise=None,
        fees_complete=False,
        temporary_databases_removed=True,
        runtime_integration=False,
        live_evidence_assessed=False,
        risk_gate_input_ready=False,
        orders_sent_to_upstox=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False),indent=2))


if __name__=="__main__":
    main()

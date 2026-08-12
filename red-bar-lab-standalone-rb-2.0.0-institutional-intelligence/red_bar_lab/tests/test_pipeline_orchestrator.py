from red_bar_lab.pipeline.orchestrator import (
    RedBarIntelligencePipelineOrchestrator,
)


class FakeDB:
    def read_signal_attempts(self, instrument_key, trading_date):
        return [
            {
                "signal_id": "SIG-1",
                "confirmation_timestamp": "2026-08-07T10:00:00+05:30",
            },
            {
                "signal_id": "SIG-2",
                "confirmation_timestamp": "2026-08-07T11:00:00+05:30",
            },
        ]

    def read_market_context_by_signal(self, signal_id):
        return {"signal_id": signal_id}

    def read_volume_structure_by_signal(self, signal_id):
        return {"signal_id": signal_id}

    def read_option_context_by_signal(self, signal_id):
        if signal_id == "SIG-1":
            return {"signal_id": signal_id, "entry_aligned": 1}
        return None


def test_pipeline_profiles_core_vs_hybrid():
    orchestrator = RedBarIntelligencePipelineOrchestrator(
        historical=None,
        database=FakeDB(),
        settings=None,
    )
    states = orchestrator.evaluate_day(
        instrument_key="NIFTY",
        trading_date="2026-08-07",
    )

    assert len(states) == 2
    assert all(state.core_eligible for state in states)
    assert states[0].hybrid_eligible is True
    assert states[1].hybrid_eligible is False

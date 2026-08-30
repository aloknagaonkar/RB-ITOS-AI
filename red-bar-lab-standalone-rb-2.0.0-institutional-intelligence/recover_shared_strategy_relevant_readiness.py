from pathlib import Path

ROOT = Path(".")
ADAPTERS = ROOT / "red_bar_lab/services/historical_strategy_adapters.py"
RUNNER = ROOT / "red_bar_lab/services/historical_strategy_runner.py"
UI = ROOT / "red_bar_lab/ui/historical_strategy_validation.py"
TEST = ROOT / "red_bar_lab/tests/test_historical_strategy_readiness.py"

adapter_text = ADAPTERS.read_text(encoding="utf-8")

if "audit: Any | None = None" not in adapter_text:
    old = "def _normalize_result(trading_date: date, result: Any) -> DayValidationResult:"
    new = (
        "def _normalize_result(\n"
        "    trading_date: date,\n"
        "    result: Any,\n"
        "    audit: Any | None = None,\n"
        ") -> DayValidationResult:"
    )
    if old not in adapter_text:
        raise RuntimeError("adapter normalize signature not found")
    adapter_text = adapter_text.replace(old, new, 1)
    print("Applied: adapter normalize signature")
else:
    print("Already applied: adapter normalize signature")

old_tail = '''        oi_coverage_pct=float(getattr(result, 'option_oi_coverage_pct', 0.0) or 0.0),
    )
'''
new_tail = '''        oi_coverage_pct=float(getattr(result, 'option_oi_coverage_pct', 0.0) or 0.0),
        global_replay_ready=bool(
            getattr(audit, 'global_replay_ready', ready)
        ),
        strategy_relevant_status=str(
            getattr(audit, 'relevant_status', 'NOT_EVALUATED')
        ),
        strategy_relevant_reason=str(
            getattr(audit, 'relevant_reason', '')
        ),
        relevant_contracts=int(
            getattr(audit, 'relevant_contracts', 0) or 0
        ),
        relevant_ce_contracts=int(
            getattr(audit, 'relevant_ce_contracts', 0) or 0
        ),
        relevant_pe_contracts=int(
            getattr(audit, 'relevant_pe_contracts', 0) or 0
        ),
        relevant_complete_contracts=int(
            getattr(audit, 'relevant_complete_contracts', 0) or 0
        ),
        relevant_candle_coverage_pct=float(
            getattr(audit, 'relevant_candle_coverage_pct', 0.0) or 0.0
        ),
        relevant_oi_coverage_pct=float(
            getattr(audit, 'relevant_oi_coverage_pct', 0.0) or 0.0
        ),
        missing_relevant_contracts=int(
            getattr(audit, 'missing_relevant_contracts', 0) or 0
        ),
    )
'''
if "strategy_relevant_status=" not in adapter_text:
    if old_tail not in adapter_text:
        raise RuntimeError("adapter return tail not found")
    adapter_text = adapter_text.replace(old_tail, new_tail, 1)
    print("Applied: adapter diagnostic fields")
else:
    print("Already applied: adapter diagnostic fields")

old_classes = '''class DRIHistoricalStrategyAdapter:
    adapter_id = 'DRI_REPLAY'
    research_only = True

    def __init__(self, replay_service) -> None:
        self.replay_service = replay_service

    def run_day(self, instrument_key: str, trading_date: date) -> DayValidationResult:
        return _normalize_result(trading_date, self.replay_service.run_day(instrument_key, trading_date))


class RedBarHistoricalStrategyAdapter:
    adapter_id = 'RED_BAR_REPLAY'
    research_only = True

    def __init__(self, replay_service) -> None:
        self.replay_service = replay_service

    def run_day(self, instrument_key: str, trading_date: date) -> DayValidationResult:
        return _normalize_result(trading_date, self.replay_service.run_day(instrument_key, trading_date))
'''
new_classes = '''class _ResearchOnlyHistoricalStrategyAdapter:
    research_only = True

    def __init__(self, replay_service, readiness_service=None) -> None:
        self.replay_service = replay_service
        self.readiness_service = readiness_service

    def run_day(self, instrument_key: str, trading_date: date) -> DayValidationResult:
        audit = (
            self.readiness_service.inspect_day(instrument_key, trading_date)
            if self.readiness_service is not None
            else None
        )
        if audit is not None and not audit.effective_ready:
            return DayValidationResult(
                trading_date=trading_date,
                ready=False,
                fidelity=audit.global_fidelity,
                readiness_reason=audit.global_reason,
                coverage_basis=audit.coverage_basis,
                global_replay_ready=False,
                strategy_relevant_status=audit.relevant_status,
                strategy_relevant_reason=audit.relevant_reason,
                relevant_contracts=audit.relevant_contracts,
                relevant_ce_contracts=audit.relevant_ce_contracts,
                relevant_pe_contracts=audit.relevant_pe_contracts,
                relevant_complete_contracts=audit.relevant_complete_contracts,
                relevant_candle_coverage_pct=audit.relevant_candle_coverage_pct,
                relevant_oi_coverage_pct=audit.relevant_oi_coverage_pct,
                missing_relevant_contracts=audit.missing_relevant_contracts,
            )
        result = self.replay_service.run_day(instrument_key, trading_date)
        return _normalize_result(trading_date, result, audit)


class DRIHistoricalStrategyAdapter(_ResearchOnlyHistoricalStrategyAdapter):
    adapter_id = 'DRI_REPLAY'


class RedBarHistoricalStrategyAdapter(_ResearchOnlyHistoricalStrategyAdapter):
    adapter_id = 'RED_BAR_REPLAY'
'''
if "class _ResearchOnlyHistoricalStrategyAdapter:" not in adapter_text:
    if old_classes not in adapter_text:
        raise RuntimeError("compact adapter class block not found")
    adapter_text = adapter_text.replace(old_classes, new_classes, 1)
    print("Applied: shared adapter readiness preflight")
else:
    print("Already applied: shared adapter readiness preflight")

ADAPTERS.write_text(adapter_text, encoding="utf-8", newline="\n")

runner_text = RUNNER.read_text(encoding="utf-8")
if "HistoricalStrategyReadinessService" not in runner_text:
    marker = "from red_bar_lab.services.historical_strategy_validation import ("
    if marker not in runner_text:
        raise RuntimeError("runner import marker not found")
    runner_text = runner_text.replace(
        marker,
        "from red_bar_lab.services.historical_strategy_readiness import (\n"
        "    HistoricalStrategyReadinessService,\n"
        ")\n" + marker,
        1,
    )
    print("Applied: runner readiness import")
else:
    print("Already applied: runner readiness import")

old_engine = '''    return HistoricalStrategyValidationEngine(
        registry or default_strategy_registry(),
        (
            DRIHistoricalStrategyAdapter(dri_replay),
            RedBarHistoricalStrategyAdapter(red_bar_replay),
        ),
    )
'''
new_engine = '''    readiness = HistoricalStrategyReadinessService(
        option_chain_sync,
        replay_reader,
    )
    return HistoricalStrategyValidationEngine(
        registry or default_strategy_registry(),
        (
            DRIHistoricalStrategyAdapter(
                dri_replay,
                readiness_service=readiness,
            ),
            RedBarHistoricalStrategyAdapter(
                red_bar_replay,
                readiness_service=readiness,
            ),
        ),
    )
'''
if "readiness_service=readiness" not in runner_text:
    if old_engine not in runner_text:
        raise RuntimeError("runner engine block not found")
    runner_text = runner_text.replace(old_engine, new_engine, 1)
    print("Applied: runner shared readiness wiring")
else:
    print("Already applied: runner shared readiness wiring")

RUNNER.write_text(runner_text, encoding="utf-8", newline="\n")

ui_text = UI.read_text(encoding="utf-8")
old_ui = '''                    "OI Coverage %": day.oi_coverage_pct,
                    "Replay Rows": len(day.rows),
                    "Readiness Reason": day.readiness_reason,
'''
new_ui = '''                    "OI Coverage %": day.oi_coverage_pct,
                    "Global Gate": (
                        "PASS" if day.global_replay_ready else "BLOCK"
                    ),
                    "Relevant Audit": day.strategy_relevant_status,
                    "Relevant Contracts": day.relevant_contracts,
                    "Relevant CE": day.relevant_ce_contracts,
                    "Relevant PE": day.relevant_pe_contracts,
                    "Relevant Complete": day.relevant_complete_contracts,
                    "Relevant Candle %": day.relevant_candle_coverage_pct,
                    "Relevant OI %": day.relevant_oi_coverage_pct,
                    "Missing Relevant": day.missing_relevant_contracts,
                    "Replay Rows": len(day.rows),
                    "Readiness Reason": day.readiness_reason,
                    "Relevant Audit Reason": day.strategy_relevant_reason,
'''
if '"Relevant Audit": day.strategy_relevant_status' not in ui_text:
    if old_ui not in ui_text:
        raise RuntimeError("UI readiness row block not found")
    ui_text = ui_text.replace(old_ui, new_ui, 1)
    print("Applied: UI shared readiness columns")
else:
    print("Already applied: UI shared readiness columns")

UI.write_text(ui_text, encoding="utf-8", newline="\n")
TEST.write_text('from datetime import date\nfrom types import SimpleNamespace\n\nimport pandas as pd\n\nfrom red_bar_lab.services.historical_strategy_adapters import (\n    DRIHistoricalStrategyAdapter,\n)\nfrom red_bar_lab.services.historical_strategy_readiness import (\n    HistoricalStrategyReadinessService,\n)\n\n\nclass FakeReader:\n    def read_day(self, instrument_key, trading_date, interval_minutes=1):\n        return pd.DataFrame(\n            {\n                "open": [100.0, 101.0],\n                "high": [102.0, 103.0],\n                "low": [99.0, 100.0],\n                "close": [101.0, 102.0],\n            }\n        )\n\n\ndef _contract(symbol, side, strike):\n    return SimpleNamespace(\n        symbol=symbol,\n        option_type=side,\n        strike=strike,\n        expected_bars=100,\n        stored_bars=100,\n        oi_bars=100,\n        candle_coverage_pct=100.0,\n        missing_bars=0,\n    )\n\n\nclass GloballyBlockedCoverage:\n    replay_ready = False\n    fidelity = "UNRELIABLE_OPTION_REPLAY"\n    reason = "Full-chain coverage is below the authoritative threshold."\n    contracts = (\n        _contract("CE100", "CE", 100.0),\n        _contract("PE100", "PE", 100.0),\n        _contract("CE105", "CE", 105.0),\n        _contract("PE105", "PE", 105.0),\n    )\n\n\nclass FakeSync:\n    def validate_day(self, instrument_key, trading_date):\n        return GloballyBlockedCoverage()\n\n\ndef test_relevant_high_never_overrides_global_replay_gate():\n    service = HistoricalStrategyReadinessService(FakeSync(), FakeReader())\n    audit = service.inspect_day("NIFTY", date(2026, 8, 11))\n\n    assert audit.relevant_status == "STRATEGY_RELEVANT_COVERAGE_HIGH"\n    assert audit.global_replay_ready is False\n    assert audit.effective_ready is False\n    assert audit.coverage_basis == "BLOCKED"\n\n\nclass NeverRunReplay:\n    def __init__(self):\n        self.called = False\n\n    def run_day(self, instrument_key, trading_date):\n        self.called = True\n        raise AssertionError("Blocked replay must not run.")\n\n\nclass FakeReadiness:\n    def inspect_day(self, instrument_key, trading_date):\n        return SimpleNamespace(\n            effective_ready=False,\n            global_replay_ready=False,\n            global_fidelity="UNRELIABLE_OPTION_REPLAY",\n            global_reason="GLOBAL_BLOCK",\n            coverage_basis="BLOCKED",\n            relevant_status="STRATEGY_RELEVANT_COVERAGE_HIGH",\n            relevant_reason="Diagnostic only.",\n            relevant_contracts=4,\n            relevant_ce_contracts=2,\n            relevant_pe_contracts=2,\n            relevant_complete_contracts=4,\n            relevant_candle_coverage_pct=100.0,\n            relevant_oi_coverage_pct=100.0,\n            missing_relevant_contracts=0,\n        )\n\n\ndef test_adapter_returns_blocked_diagnostics_without_running_replay():\n    replay = NeverRunReplay()\n    adapter = DRIHistoricalStrategyAdapter(\n        replay,\n        readiness_service=FakeReadiness(),\n    )\n\n    result = adapter.run_day("NIFTY", date(2026, 8, 11))\n\n    assert result.ready is False\n    assert result.global_replay_ready is False\n    assert result.strategy_relevant_status == (\n        "STRATEGY_RELEVANT_COVERAGE_HIGH"\n    )\n    assert result.coverage_basis == "BLOCKED"\n    assert replay.called is False\n', encoding="utf-8", newline="\n")
print(f"Created/updated: {TEST}")
print("Shared readiness recovery completed.")

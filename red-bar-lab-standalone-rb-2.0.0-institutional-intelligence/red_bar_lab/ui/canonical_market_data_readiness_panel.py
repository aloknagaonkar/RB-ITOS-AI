from __future__ import annotations

import pandas as pd

from red_bar_lab.domain.red_bar_v2 import OptionSide
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_observability import (
    MarketDataReadinessObservabilityService,
)


def _text(value) -> str:
    if value is None: return "—"
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def render_canonical_market_data_readiness_panel(st, settings) -> None:
    st.markdown("### 11. Market-data provider readiness")
    st.warning("READ ONLY — this panel reads one sanitized persisted report. It does not construct a provider, call a network, initialize SQLite, reserve a bundle or submit any order.")
    observation = MarketDataReadinessObservabilityService(
        settings.market_data_readiness_state_path,
        stale_after_seconds=max(settings.red_bar_v2_market_data_readiness_max_quote_age_seconds * 2.0, 60.0),
    ).load(enabled=settings.red_bar_v2_market_data_readiness_enabled)
    st.metric("Readiness report state", observation.status)
    if observation.report is None:
        messages = {
            "READINESS_DISABLED": "The independent provider readiness probe is disabled.",
            "READINESS_NOT_RUN": "Readiness is enabled but no verified report has been persisted.",
            "READINESS_REPORT_CORRUPT": "The readiness report failed schema or digest validation, or uses an unsupported schema.",
            "READINESS_REPORT_UNAVAILABLE": "The readiness report could not be read.",
        }
        message = messages.get(observation.status, "No verified readiness report is available.")
        if observation.status == "READINESS_REPORT_CORRUPT": st.error(message)
        else: st.info(message)
        return
    report = observation.report
    fields = [
        ("Provider", report.provider), ("Readiness status", report.status.value), ("Reason code", report.reason_code),
        ("Failure stage", report.failure_stage.value), ("Evaluated timestamp", _text(report.evaluated_at)),
        ("NIFTY spot", _text(report.spot_price)), ("Spot provider timestamp", _text(report.spot_timestamp)),
        ("Expiry", _text(report.expiry)), ("Detected strike interval", _text(report.strike_interval)),
        ("ATM strike", _text(report.atm_strike)),
        ("Expected / observed / ready", f"{report.expected_contract_count} / {report.observed_contract_count} / {report.ready_contract_count}"),
        ("CE / PE coverage", f"{report.ce_coverage} / {report.pe_coverage}"), ("Report integrity", observation.integrity),
        ("Report age seconds", _text(round(observation.age_seconds, 2) if observation.age_seconds is not None else None)),
    ]
    st.dataframe(pd.DataFrame(fields, columns=["Field", "Verified value"], dtype="string"), hide_index=True, use_container_width=True)

    if report.diagnostic is not None:
        diagnostic = report.diagnostic
        diagnostic_fields = [
            ("Failure stage", report.failure_stage.value),
            ("Reason code", diagnostic.reason_code),
            ("Received count", diagnostic.received_count),
            ("Normalized count", diagnostic.normalized_count),
            ("Rejected count", diagnostic.rejected_count),
            ("CE count", diagnostic.ce_count),
            ("PE count", diagnostic.pe_count),
            ("Common expiry count", diagnostic.common_expiry_count),
            ("Unique strike count", diagnostic.unique_strike_count),
            ("Rejected field", diagnostic.rejected_field),
            ("Rejected type", diagnostic.rejected_type),
        ]
        diagnostic_fields = [(name, _text(value)) for name, value in diagnostic_fields if value is not None]
        st.markdown("#### Sanitized diagnostic")
        st.dataframe(pd.DataFrame(diagnostic_fields, columns=["Diagnostic field", "Sanitized value"], dtype="string"), hide_index=True, use_container_width=True)

    by_cell = {(row.strike, row.option_side): row for row in report.contracts}
    strikes = sorted({row.strike for row in report.contracts})
    rows = []
    for strike in strikes:
        ce = by_cell.get((strike, OptionSide.CE)); pe = by_cell.get((strike, OptionSide.PE))
        rows.append({
            "Strike": strike,
            "CE moneyness": ce.moneyness if ce else "—",
            "CE quote": ce.last_price if ce else None,
            "CE status": ce.status.value if ce else "MISSING",
            "PE moneyness": pe.moneyness if pe else "—",
            "PE quote": pe.last_price if pe else None,
            "PE status": pe.status.value if pe else "MISSING",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

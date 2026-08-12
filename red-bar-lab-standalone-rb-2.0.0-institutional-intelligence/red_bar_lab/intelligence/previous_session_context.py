from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine
from red_bar_lab.intelligence.contract_quality import ContractQualityEngine
from red_bar_lab.intelligence.institutional_flow import InstitutionalOptionFlowEngine
from red_bar_lab.intelligence.oi_velocity import OIVelocityEngine
from red_bar_lab.options.context import _max_pain_strike


@dataclass(frozen=True)
class PreviousSessionContext:
    previous_trading_date: str | None
    snapshot_count: int
    closing_bias: str
    buying_strength_pct: float
    selling_strength_pct: float
    closing_flow_score: float
    closing_pcr: float | None
    closing_max_pain: float | None
    dominant_strike: float | None
    dominant_side: str | None
    dominant_oi: float | None
    carry_forward_bias: str
    carry_forward_confidence_pct: float
    opening_narrative: str
    status: str
    reason: str
    execution_impact: str = "NONE"


class PreviousSessionContextService:
    """Build Sprint-3 context from the previous completed ONLINE option session only.

    This service is advisory/read-only. It reuses frozen Sprint-1/Sprint-2 engines
    for previous-session evidence and never writes execution, candidate, committee,
    portfolio, queue or exit state.
    """

    def __init__(self, database) -> None:
        self.database = database

    @staticmethod
    def _artifact(path_value: object) -> pd.DataFrame:
        if not path_value:
            return pd.DataFrame()
        try:
            path = Path(str(path_value))
            return pd.read_csv(path) if path.exists() else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _num(value: object) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _closing_chain_summary(cls, frame: pd.DataFrame) -> tuple[float | None, float | None, float | None, str | None, float | None]:
        if frame is None or frame.empty or "strike" not in frame.columns:
            return None, None, None, None, None
        work = frame.copy()
        for column in ("strike", "call_oi", "put_oi"):
            if column in work.columns:
                work[column] = pd.to_numeric(work[column], errors="coerce")
        call_total = float(work.get("call_oi", pd.Series(dtype=float)).fillna(0.0).sum())
        put_total = float(work.get("put_oi", pd.Series(dtype=float)).fillna(0.0).sum())
        pcr = put_total / call_total if call_total > 0 else None
        max_pain = _max_pain_strike(work) if {"call_oi", "put_oi"}.issubset(work.columns) else None

        dominant_strike = dominant_side = dominant_oi = None
        best: tuple[float, float, str] | None = None
        for _, row in work.dropna(subset=["strike"]).iterrows():
            strike = float(row["strike"])
            for side, column in (("CALL", "call_oi"), ("PUT", "put_oi")):
                oi = cls._num(row.get(column)) or 0.0
                candidate = (oi, strike, side)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best is not None:
            dominant_oi, dominant_strike, dominant_side = best
        return pcr, max_pain, dominant_strike, dominant_side, dominant_oi

    @staticmethod
    def _bias_from_strength(net_strength: float) -> str:
        if net_strength > 5.0:
            return "BULLISH"
        if net_strength < -5.0:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _pcr_vote(pcr: float | None) -> str:
        if pcr is None:
            return "NEUTRAL"
        if pcr >= 1.05:
            return "BULLISH"
        if pcr <= 0.95:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _dominant_vote(side: str | None) -> str:
        if side == "PUT":
            return "BULLISH"
        if side == "CALL":
            return "BEARISH"
        return "NEUTRAL"

    @classmethod
    def _carry_forward(cls, closing_bias: str, pcr: float | None, dominant_side: str | None) -> tuple[str, float, tuple[str, str, str]]:
        votes = (closing_bias, cls._pcr_vote(pcr), cls._dominant_vote(dominant_side))
        bullish = votes.count("BULLISH")
        bearish = votes.count("BEARISH")
        if bullish >= 2:
            bias = "BULLISH"
            confidence = bullish / 3.0 * 100.0
        elif bearish >= 2:
            bias = "BEARISH"
            confidence = bearish / 3.0 * 100.0
        else:
            bias = "NEUTRAL"
            confidence = max(bullish, bearish) / 3.0 * 100.0
        return bias, round(confidence, 2), votes

    @staticmethod
    def _narrative(previous_date: str, closing_bias: str, buy: float, sell: float, pcr: float | None,
                   max_pain: float | None, dominant_strike: float | None, dominant_side: str | None,
                   carry_bias: str, carry_confidence: float, votes: tuple[str, str, str]) -> str:
        pcr_text = "unavailable" if pcr is None else f"{pcr:.2f}"
        pain_text = "unavailable" if max_pain is None else f"{max_pain:.0f}"
        dominant_text = "unavailable" if dominant_strike is None else f"{dominant_strike:.0f} {dominant_side or ''}".strip()
        return (
            f"Previous session {previous_date} closed {closing_bias}: buying strength {buy:.1f}% vs selling strength {sell:.1f}%. "
            f"Closing PCR was {pcr_text}, Max Pain {pain_text}, and dominant OI strike {dominant_text}. "
            f"Carry-forward bias is {carry_bias} at {carry_confidence:.1f}% vote agreement "
            f"(strength/PCR/dominant-OI votes: {votes[0]}/{votes[1]}/{votes[2]}). "
            "Use this as an opening expectation only; execution impact remains NONE."
        )

    def latest_before(self, instrument_key: str, trading_date: str) -> PreviousSessionContext:
        target = date.fromisoformat(str(trading_date))
        start = target - timedelta(days=21)
        end = target - timedelta(days=1)
        history = self.database.read_option_chain_history(
            instrument_key,
            start.isoformat(),
            end.isoformat(),
            limit=5000,
        )
        usable: list[tuple[pd.Timestamp, dict[str, object], pd.DataFrame]] = []
        for meta in history:
            if str(meta.get("collector_mode") or "").upper() != "ONLINE":
                continue
            frame = self._artifact(meta.get("chain_artifact_path"))
            if frame.empty:
                continue
            try:
                ts = pd.Timestamp(meta.get("snapshot_timestamp"))
            except Exception:
                continue
            if pd.isna(ts):
                continue
            if ts.tzinfo is None:
                ts = ts.tz_localize("Asia/Kolkata")
            else:
                ts = ts.tz_convert("Asia/Kolkata")
            if ts.date() >= target:
                continue
            usable.append((ts, dict(meta), frame))

        if not usable:
            return PreviousSessionContext(
                None, 0, "UNKNOWN", 0.0, 0.0, 0.0, None, None, None, None, None,
                "NEUTRAL", 0.0,
                "Previous-session ONLINE option-chain context is not available yet.",
                "WAITING",
                "No persisted ONLINE option-chain snapshots were found before the selected trading date.",
            )

        usable.sort(key=lambda item: item[0])
        previous_date = usable[-1][0].date()
        session = [item for item in usable if item[0].date() == previous_date]
        session.sort(key=lambda item: item[0])
        latest_ts, latest_meta, latest = session[-1]

        pcr, max_pain, dominant_strike, dominant_side, dominant_oi = self._closing_chain_summary(latest)
        buy = sell = net = 0.0
        if len(session) >= 2:
            previous_ts, _, previous = session[-2]
            flow = InstitutionalOptionFlowEngine.evaluate_frames(
                latest,
                previous,
                snapshot_timestamp=latest_ts.isoformat(),
                previous_snapshot_timestamp=previous_ts.isoformat(),
                option_expiry=str(latest_meta.get("option_expiry") or "") or None,
            )
            time_series = [(ts, frame) for ts, _, frame in session]
            velocity = OIVelocityEngine.evaluate(time_series)
            velocity_by_key = {(row.strike, row.option_type): row for row in velocity}
            quality = ContractQualityEngine.evaluate(latest)
            quality_by_key = {(row.strike, row.option_type): row for row in quality}
            strength = BuySellStrengthEngine.evaluate(flow.rows, velocity_by_key, quality_by_key)
            buy = float(strength.buying_strength_pct)
            sell = float(strength.selling_strength_pct)
            net = float(strength.net_strength)

        closing_bias = self._bias_from_strength(net)
        carry_bias, carry_confidence, votes = self._carry_forward(closing_bias, pcr, dominant_side)
        narrative = self._narrative(
            previous_date.isoformat(), closing_bias, buy, sell, pcr, max_pain,
            dominant_strike, dominant_side, carry_bias, carry_confidence, votes,
        )
        status = "READY" if len(session) >= 2 else "PARTIAL"
        reason = (
            f"Built from {len(session)} persisted ONLINE snapshots from previous trading session {previous_date.isoformat()}."
            if len(session) >= 2
            else f"Only one ONLINE snapshot exists for {previous_date.isoformat()}; closing PCR/Max Pain are available but flow strength needs two snapshots."
        )
        return PreviousSessionContext(
            previous_date.isoformat(), len(session), closing_bias,
            round(buy, 2), round(sell, 2), round(net, 2),
            round(pcr, 4) if pcr is not None else None,
            round(max_pain, 2) if max_pain is not None else None,
            round(dominant_strike, 2) if dominant_strike is not None else None,
            dominant_side,
            round(dominant_oi, 2) if dominant_oi is not None else None,
            carry_bias, carry_confidence, narrative, status, reason,
        )

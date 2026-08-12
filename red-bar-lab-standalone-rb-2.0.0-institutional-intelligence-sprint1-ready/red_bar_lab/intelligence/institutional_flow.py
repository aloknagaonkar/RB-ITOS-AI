from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class InstitutionalFlowRow:
    strike: float
    option_type: str
    premium: float | None
    premium_change_pct: float | None
    oi: float | None
    oi_change_pct: float | None
    volume: float | None
    behaviour: str
    activity: str
    directional_bias: str
    confidence_pct: float
    evidence: str

    def as_dict(self) -> dict[str, object]:
        return {"Strike": self.strike, "Side": self.option_type, "Premium": self.premium,
            "Premium Change %": self.premium_change_pct, "OI": self.oi, "OI Change %": self.oi_change_pct,
            "Volume": self.volume, "OI Behaviour": self.behaviour, "Institutional Activity": self.activity,
            "Directional Bias": self.directional_bias, "Confidence %": self.confidence_pct, "Evidence": self.evidence}


@dataclass(frozen=True)
class InstitutionalFlowSnapshot:
    snapshot_timestamp: str | None
    previous_snapshot_timestamp: str | None
    option_expiry: str | None
    rows: tuple[InstitutionalFlowRow, ...]
    bullish_flow_pct: float
    bearish_flow_pct: float
    neutral_flow_pct: float
    dominant_activity: str
    strongest_bullish: str | None
    strongest_bearish: str | None
    status: str
    reason: str


class InstitutionalOptionFlowEngine:
    """Read-only two-snapshot institutional option-flow classifier."""

    PRICE_NOISE_PCT = 0.15
    OI_NOISE_PCT = 0.50

    @staticmethod
    def _num(value: object) -> float | None:
        try:
            return None if value is None or pd.isna(value) else float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _pct(current, previous):
        if current is None or previous is None or previous == 0:
            return None
        return (current - previous) / abs(previous) * 100.0

    @staticmethod
    def _artifact(path_value: object) -> pd.DataFrame:
        if not path_value:
            return pd.DataFrame()
        try:
            path = Path(str(path_value))
            return pd.read_csv(path) if path.exists() else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    @classmethod
    def classify_oi_behaviour(cls, price_change_pct, oi_change_pct) -> str:
        if price_change_pct is None or oi_change_pct is None:
            return "UNKNOWN"
        p = 0.0 if abs(price_change_pct) < cls.PRICE_NOISE_PCT else price_change_pct
        o = 0.0 if abs(oi_change_pct) < cls.OI_NOISE_PCT else oi_change_pct
        if o > 0 and p > 0: return "LONG_BUILDUP"
        if o > 0 and p < 0: return "SHORT_BUILDUP"
        if o < 0 and p > 0: return "SHORT_COVERING"
        if o < 0 and p < 0: return "LONG_UNWINDING"
        return "NEUTRAL"

    @staticmethod
    def classify_activity(option_type: str, behaviour: str) -> str:
        mapping = {
            ("CE", "LONG_BUILDUP"): "CALL_BUYING", ("CE", "SHORT_BUILDUP"): "CALL_WRITING",
            ("CE", "SHORT_COVERING"): "CALL_WRITER_COVERING", ("CE", "LONG_UNWINDING"): "CALL_BUYER_UNWINDING",
            ("PE", "LONG_BUILDUP"): "PUT_BUYING", ("PE", "SHORT_BUILDUP"): "PUT_WRITING",
            ("PE", "SHORT_COVERING"): "PUT_WRITER_COVERING", ("PE", "LONG_UNWINDING"): "PUT_BUYER_UNWINDING",
        }
        return mapping.get((option_type, behaviour), "NO_CLEAR_ACTIVITY")

    @staticmethod
    def directional_bias(activity: str) -> str:
        bullish = {"CALL_BUYING", "PUT_WRITING", "PUT_BUYER_UNWINDING", "CALL_WRITER_COVERING"}
        bearish = {"PUT_BUYING", "CALL_WRITING", "CALL_BUYER_UNWINDING", "PUT_WRITER_COVERING"}
        return "BULLISH" if activity in bullish else "BEARISH" if activity in bearish else "NEUTRAL"

    @staticmethod
    def confidence(price_change_pct, oi_change_pct, volume) -> float:
        if price_change_pct is None or oi_change_pct is None:
            return 0.0
        p = min(35.0, abs(price_change_pct) / 2.0 * 35.0)
        o = min(45.0, abs(oi_change_pct) / 10.0 * 45.0)
        v = 0.0 if volume is None else min(20.0, max(0.0, volume) / 100000.0 * 20.0)
        return round(min(100.0, p + o + v), 2)

    @classmethod
    def _side_row(cls, current, previous, side):
        prefix = "call" if side == "CE" else "put"
        strike = cls._num(current.get("strike")) or 0.0
        premium, prior_premium = cls._num(current.get(f"{prefix}_ltp")), cls._num(previous.get(f"{prefix}_ltp"))
        oi, prior_oi = cls._num(current.get(f"{prefix}_oi")), cls._num(previous.get(f"{prefix}_oi"))
        volume = cls._num(current.get(f"{prefix}_volume"))
        price_pct, oi_pct = cls._pct(premium, prior_premium), cls._pct(oi, prior_oi)
        behaviour = cls.classify_oi_behaviour(price_pct, oi_pct)
        activity = cls.classify_activity(side, behaviour)
        evidence = (f"Premium {price_pct:+.2f}%" if price_pct is not None else "Premium change unavailable") + "; " + (f"OI {oi_pct:+.2f}%" if oi_pct is not None else "OI change unavailable")
        return InstitutionalFlowRow(round(strike, 2), side, premium, round(price_pct, 3) if price_pct is not None else None,
            oi, round(oi_pct, 3) if oi_pct is not None else None, volume, behaviour, activity,
            cls.directional_bias(activity), cls.confidence(price_pct, oi_pct, volume), evidence)

    @classmethod
    def evaluate_frames(cls, current, previous, *, snapshot_timestamp=None, previous_snapshot_timestamp=None, option_expiry=None):
        if current is None or previous is None or current.empty or previous.empty or "strike" not in current.columns or "strike" not in previous.columns:
            return InstitutionalFlowSnapshot(snapshot_timestamp, previous_snapshot_timestamp, option_expiry, (), 0.0, 0.0, 100.0,
                "INSUFFICIENT_DATA", None, None, "WAITING", "Two non-empty option-chain snapshots with strike data are required.")
        cur, prev = current.copy(), previous.copy()
        cur["strike"] = pd.to_numeric(cur["strike"], errors="coerce"); prev["strike"] = pd.to_numeric(prev["strike"], errors="coerce")
        prev_by_strike = {float(r["strike"]): r for _, r in prev.dropna(subset=["strike"]).iterrows()}
        rows = []
        for _, row in cur.dropna(subset=["strike"]).iterrows():
            prior = prev_by_strike.get(float(row["strike"]))
            if prior is not None:
                rows.extend((cls._side_row(row, prior, "CE"), cls._side_row(row, prior, "PE")))
        if not rows:
            return InstitutionalFlowSnapshot(snapshot_timestamp, previous_snapshot_timestamp, option_expiry, (), 0.0, 0.0, 100.0,
                "INSUFFICIENT_DATA", None, None, "WAITING", "No strikes overlapped between consecutive snapshots.")
        weighted = {"BULLISH": 0.0, "BEARISH": 0.0, "NEUTRAL": 0.0}
        activities = {}
        for row in rows:
            w = max(1.0, row.confidence_pct); weighted[row.directional_bias] += w; activities[row.activity] = activities.get(row.activity, 0.0) + w
        total = sum(weighted.values()) or 1.0
        bullish, bearish = round(weighted["BULLISH"] / total * 100.0, 2), round(weighted["BEARISH"] / total * 100.0, 2)
        neutral = round(max(0.0, 100.0 - bullish - bearish), 2)
        br = sorted((r for r in rows if r.directional_bias == "BULLISH"), key=lambda r: r.confidence_pct, reverse=True)
        sr = sorted((r for r in rows if r.directional_bias == "BEARISH"), key=lambda r: r.confidence_pct, reverse=True)
        return InstitutionalFlowSnapshot(snapshot_timestamp, previous_snapshot_timestamp, option_expiry, tuple(rows), bullish, bearish, neutral,
            max(activities, key=activities.get) if activities else "NO_CLEAR_ACTIVITY",
            f"{br[0].strike:.0f} {br[0].option_type}" if br else None, f"{sr[0].strike:.0f} {sr[0].option_type}" if sr else None,
            "READY", f"Compared {len(rows)//2} strikes across two consecutive captured snapshots.")


class InstitutionalFlowService:
    def __init__(self, database) -> None:
        self.database = database

    def latest(self, instrument_key: str, trading_date: str) -> InstitutionalFlowSnapshot:
        history = self.database.read_option_chain_history(instrument_key, trading_date, trading_date, limit=2000)
        usable = []
        for meta in history:
            if str(meta.get("collector_mode") or "").upper() != "ONLINE": continue
            frame = InstitutionalOptionFlowEngine._artifact(meta.get("chain_artifact_path"))
            if frame.empty: continue
            usable.append((pd.Timestamp(meta.get("snapshot_timestamp")), meta, frame))
        usable.sort(key=lambda x: x[0])
        if len(usable) < 2:
            return InstitutionalFlowSnapshot(None, None, None, (), 0.0, 0.0, 100.0, "INSUFFICIENT_DATA", None, None,
                "WAITING", "At least two ONLINE option-chain snapshots are required for institutional flow classification.")
        pts, _, previous = usable[-2]; cts, meta, current = usable[-1]
        return InstitutionalOptionFlowEngine.evaluate_frames(current, previous, snapshot_timestamp=cts.isoformat(),
            previous_snapshot_timestamp=pts.isoformat(), option_expiry=str(meta.get("option_expiry") or "") or None)

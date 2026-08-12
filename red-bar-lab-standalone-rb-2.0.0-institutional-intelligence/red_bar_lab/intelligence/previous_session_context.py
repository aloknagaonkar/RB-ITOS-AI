from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd

from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine
from red_bar_lab.intelligence.contract_quality import ContractQualityEngine
from red_bar_lab.intelligence.institutional_flow import InstitutionalOptionFlowEngine
from red_bar_lab.intelligence.oi_velocity import OIVelocityEngine
from red_bar_lab.options.context import _max_pain_strike


def _safe_path_part(value: object) -> str:
    return str(value or "").replace("|", "_").replace("/", "_").replace("\\", "_").replace(" ", "_")


@dataclass(frozen=True)
class PreviousSessionReadiness:
    target_trading_date: str
    previous_artifact_date: str | None
    online_snapshots: int
    historical_snapshots: int
    artifact_contracts: int
    adapted_snapshots: int
    status: str
    detail: str


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
    data_source: str = "NONE"


class PreviousSessionHistoricalAdapter:
    """Convert validated local expired-option candles into HISTORICAL chain snapshots.

    This is a local artifact adapter only. It performs no provider/network call and
    never labels reconstructed historical data as ONLINE. The latest two sufficiently
    populated one-minute timestamps are persisted for Sprint-3 closing-context use.
    """

    def __init__(self, database, layout) -> None:
        self.database = database
        self.layout = layout

    def _root(self, instrument_key: str, trading_day: date) -> Path:
        return (
            self.layout.settings.historical_root
            / "upstox"
            / "options"
            / _safe_path_part(instrument_key)
            / trading_day.isoformat()
        )

    @staticmethod
    def _contract_key(row: dict[str, object]) -> str:
        for key in ("instrument_key", "instrument_token", "expired_instrument_key"):
            if row.get(key):
                return str(row[key])
        return ""

    @staticmethod
    def _side(row: dict[str, object]) -> str:
        raw = str(row.get("instrument_type") or row.get("option_type") or row.get("type") or "").upper()
        symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or row.get("symbol") or "").upper()
        if raw.endswith("CE") or raw == "CE" or "CALL" in raw:
            return "CE"
        if raw.endswith("PE") or raw == "PE" or "PUT" in raw:
            return "PE"
        if "CE" in symbol[-5:]:
            return "CE"
        if "PE" in symbol[-5:]:
            return "PE"
        return raw

    @staticmethod
    def _strike(row: dict[str, object]) -> float | None:
        try:
            value = row.get("strike_price", row.get("strike"))
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _manifest(self, instrument_key: str, trading_day: date) -> dict[str, object]:
        path = self._root(instrument_key, trading_day) / "contracts.json"
        if not path.exists():
            return {"expiry": None, "contracts": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"expiry": None, "contracts": []}
        except Exception:
            return {"expiry": None, "contracts": []}

    def _find_previous_artifact_day(self, instrument_key: str, target: date) -> tuple[date | None, dict[str, object]]:
        for offset in range(1, 22):
            day = target - timedelta(days=offset)
            manifest = self._manifest(instrument_key, day)
            contracts = [row for row in manifest.get("contracts", []) if isinstance(row, dict)]
            if contracts:
                return day, manifest
        return None, {"expiry": None, "contracts": []}

    def _build_timestamp_chains(
        self,
        instrument_key: str,
        trading_day: date,
        contracts: list[dict[str, object]],
    ) -> dict[pd.Timestamp, pd.DataFrame]:
        by_timestamp: dict[pd.Timestamp, dict[float, dict[str, object]]] = {}
        candles_root = self._root(instrument_key, trading_day) / "candles"
        for contract in contracts:
            key = self._contract_key(contract)
            strike = self._strike(contract)
            side = self._side(contract)
            if not key or strike is None or side not in {"CE", "PE"}:
                continue
            path = candles_root / f"{_safe_path_part(key)}.csv"
            if not path.exists():
                continue
            try:
                frame = pd.read_csv(path)
            except Exception:
                continue
            if frame.empty or "timestamp" not in frame.columns:
                continue
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
            frame = frame.dropna(subset=["timestamp"])
            prefix = "call" if side == "CE" else "put"
            for _, candle in frame.iterrows():
                ts = pd.Timestamp(candle["timestamp"]).tz_convert("Asia/Kolkata").floor("min")
                if ts.date() != trading_day:
                    continue
                strike_row = by_timestamp.setdefault(ts, {}).setdefault(float(strike), {"strike": float(strike)})
                strike_row[f"{prefix}_ltp"] = candle.get("close")
                strike_row[f"{prefix}_oi"] = candle.get("oi")
                strike_row[f"{prefix}_volume"] = candle.get("volume")

        chains: dict[pd.Timestamp, pd.DataFrame] = {}
        for ts, strikes in by_timestamp.items():
            chain = pd.DataFrame(strikes.values()).sort_values("strike").reset_index(drop=True)
            if chain.empty:
                continue
            # Require both option sides to be represented before treating a minute as
            # a trustworthy chain snapshot. Missing individual strikes remain visible
            # as NaN rather than being fabricated.
            has_ce = "call_oi" in chain.columns and pd.to_numeric(chain["call_oi"], errors="coerce").notna().any()
            has_pe = "put_oi" in chain.columns and pd.to_numeric(chain["put_oi"], errors="coerce").notna().any()
            if has_ce and has_pe:
                chains[ts] = chain
        return chains

    def _persist_snapshot(
        self,
        instrument_key: str,
        trading_day: date,
        expiry: str | None,
        ts: pd.Timestamp,
        chain: pd.DataFrame,
    ) -> None:
        output = self._root(instrument_key, trading_day) / "sprint3_snapshots" / f"{ts.strftime('%H%M%S')}.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        chain.to_csv(output, index=False)
        snapshot_key = f"SPRINT3_HISTORICAL|{instrument_key}|{trading_day.isoformat()}|{ts.isoformat()}"
        self.database.upsert_option_chain_history({
            "snapshot_key": snapshot_key,
            "instrument_key": instrument_key,
            "trading_date": trading_day.isoformat(),
            "option_expiry": expiry,
            "snapshot_timestamp": ts.isoformat(),
            "collector_mode": "HISTORICAL",
            "chain_artifact_path": str(output),
        })

    def ensure_previous_session(self, instrument_key: str, trading_date: str) -> PreviousSessionReadiness:
        target = date.fromisoformat(str(trading_date))
        history = self.database.read_option_chain_history(
            instrument_key,
            (target - timedelta(days=21)).isoformat(),
            (target - timedelta(days=1)).isoformat(),
            limit=5000,
        )
        online = [row for row in history if str(row.get("collector_mode") or "").upper() == "ONLINE"]
        historical = [
            row for row in history
            if str(row.get("collector_mode") or "").upper() in PreviousSessionContextService.TRUSTED_HISTORICAL_MODES
        ]
        if online or historical:
            return PreviousSessionReadiness(
                target.isoformat(), None, len(online), len(historical), 0, 0, "READY",
                "Trustworthy persisted previous-session snapshots already exist; no artifact adaptation was required.",
            )

        artifact_day, manifest = self._find_previous_artifact_day(instrument_key, target)
        contracts = [row for row in manifest.get("contracts", []) if isinstance(row, dict)]
        if artifact_day is None or not contracts:
            return PreviousSessionReadiness(
                target.isoformat(), None, 0, 0, 0, 0, "BACKFILL_REQUIRED",
                "No persisted snapshots and no local historical option-contract artifacts were found. Run Historical Option Sync for a prior trading session.",
            )

        chains = self._build_timestamp_chains(instrument_key, artifact_day, contracts)
        if len(chains) < 2:
            return PreviousSessionReadiness(
                target.isoformat(), artifact_day.isoformat(), 0, 0, len(contracts), 0, "ARTIFACTS_INCOMPLETE",
                "Historical contracts exist, but fewer than two complete CE/PE one-minute chain timestamps could be reconstructed.",
            )

        selected = sorted(chains)[-2:]
        for ts in selected:
            self._persist_snapshot(
                instrument_key,
                artifact_day,
                str(manifest.get("expiry") or "") or None,
                ts,
                chains[ts],
            )
        return PreviousSessionReadiness(
            target.isoformat(), artifact_day.isoformat(), 0, 2, len(contracts), 2, "ADAPTED",
            f"Adapted the final two trustworthy one-minute historical option-chain snapshots from {artifact_day.isoformat()} and persisted them as HISTORICAL.",
        )


class PreviousSessionContextService:
    """Build Sprint-3 context from trustworthy previous-session option snapshots.

    Source precedence is deliberately explicit: ONLINE is preferred when it exists
    for the previous completed session; validated HISTORICAL/BACKFILL snapshots are
    an advisory fallback. REPLAY, synthetic and mock sources are never accepted.
    The service is read-only and has zero execution authority.
    """

    TRUSTED_HISTORICAL_MODES = frozenset({"HISTORICAL", "BACKFILL", "EXPIRED_OPTION_CANDLES"})

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
            return "BULLISH", round(bullish / 3.0 * 100.0, 2), votes
        if bearish >= 2:
            return "BEARISH", round(bearish / 3.0 * 100.0, 2), votes
        return "NEUTRAL", round(max(bullish, bearish) / 3.0 * 100.0, 2), votes

    @staticmethod
    def _narrative(previous_date: str, closing_bias: str, buy: float, sell: float, pcr: float | None,
                   max_pain: float | None, dominant_strike: float | None, dominant_side: str | None,
                   carry_bias: str, carry_confidence: float, votes: tuple[str, str, str], data_source: str) -> str:
        pcr_text = "unavailable" if pcr is None else f"{pcr:.2f}"
        pain_text = "unavailable" if max_pain is None else f"{max_pain:.0f}"
        dominant_text = "unavailable" if dominant_strike is None else f"{dominant_strike:.0f} {dominant_side or ''}".strip()
        return (
            f"Previous session {previous_date} ({data_source}) closed {closing_bias}: buying strength {buy:.1f}% vs selling strength {sell:.1f}%. "
            f"Closing PCR was {pcr_text}, Max Pain {pain_text}, and dominant OI strike {dominant_text}. "
            f"Carry-forward bias is {carry_bias} at {carry_confidence:.1f}% vote agreement "
            f"(strength/PCR/dominant-OI votes: {votes[0]}/{votes[1]}/{votes[2]}). "
            "Use this as an opening expectation only; execution impact remains NONE."
        )

    def latest_before(self, instrument_key: str, trading_date: str) -> PreviousSessionContext:
        target = date.fromisoformat(str(trading_date))
        history = self.database.read_option_chain_history(
            instrument_key, (target - timedelta(days=21)).isoformat(), (target - timedelta(days=1)).isoformat(), limit=5000
        )
        usable: list[tuple[pd.Timestamp, str, dict[str, object], pd.DataFrame]] = []
        for meta in history:
            mode = str(meta.get("collector_mode") or "").upper()
            if mode != "ONLINE" and mode not in self.TRUSTED_HISTORICAL_MODES:
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
            ts = ts.tz_localize("Asia/Kolkata") if ts.tzinfo is None else ts.tz_convert("Asia/Kolkata")
            if ts.date() >= target:
                continue
            source = "ONLINE" if mode == "ONLINE" else "HISTORICAL"
            usable.append((ts, source, dict(meta), frame))

        if not usable:
            return PreviousSessionContext(
                None, 0, "UNKNOWN", 0.0, 0.0, 0.0, None, None, None, None, None,
                "NEUTRAL", 0.0, "Previous-session option-chain context is not available yet.",
                "WAITING", "No trustworthy ONLINE or validated HISTORICAL option-chain snapshots were found before the selected trading date.",
            )

        previous_date = max(item[0].date() for item in usable)
        same_day = [item for item in usable if item[0].date() == previous_date]
        online = [item for item in same_day if item[1] == "ONLINE"]
        historical = [item for item in same_day if item[1] == "HISTORICAL"]
        session = online if online else historical
        data_source = "ONLINE" if online else "HISTORICAL"
        session.sort(key=lambda item: item[0])
        latest_ts, _, latest_meta, latest = session[-1]

        pcr, max_pain, dominant_strike, dominant_side, dominant_oi = self._closing_chain_summary(latest)
        buy = sell = net = 0.0
        if len(session) >= 2:
            previous_ts, _, _, previous = session[-2]
            flow = InstitutionalOptionFlowEngine.evaluate_frames(
                latest, previous, snapshot_timestamp=latest_ts.isoformat(),
                previous_snapshot_timestamp=previous_ts.isoformat(),
                option_expiry=str(latest_meta.get("option_expiry") or "") or None,
            )
            time_series = [(ts, frame) for ts, _, _, frame in session]
            velocity = OIVelocityEngine.evaluate(time_series)
            velocity_by_key = {(row.strike, row.option_type): row for row in velocity}
            quality = ContractQualityEngine.evaluate(latest)
            quality_by_key = {(row.strike, row.option_type): row for row in quality}
            strength = BuySellStrengthEngine.evaluate(flow.rows, velocity_by_key, quality_by_key)
            buy, sell, net = float(strength.buying_strength_pct), float(strength.selling_strength_pct), float(strength.net_strength)

        closing_bias = self._bias_from_strength(net)
        carry_bias, carry_confidence, votes = self._carry_forward(closing_bias, pcr, dominant_side)
        narrative = self._narrative(
            previous_date.isoformat(), closing_bias, buy, sell, pcr, max_pain,
            dominant_strike, dominant_side, carry_bias, carry_confidence, votes, data_source,
        )
        status = "READY" if len(session) >= 2 else "PARTIAL"
        reason = (
            f"Built from {len(session)} trustworthy {data_source} snapshots from previous trading session {previous_date.isoformat()}."
            if len(session) >= 2 else
            f"Only one trustworthy {data_source} snapshot exists for {previous_date.isoformat()}; PCR/Max Pain are available but flow strength needs two snapshots."
        )
        return PreviousSessionContext(
            previous_date.isoformat(), len(session), closing_bias,
            round(buy, 2), round(sell, 2), round(net, 2),
            round(pcr, 4) if pcr is not None else None,
            round(max_pain, 2) if max_pain is not None else None,
            round(dominant_strike, 2) if dominant_strike is not None else None,
            dominant_side, round(dominant_oi, 2) if dominant_oi is not None else None,
            carry_bias, carry_confidence, narrative, status, reason, "NONE", data_source,
        )

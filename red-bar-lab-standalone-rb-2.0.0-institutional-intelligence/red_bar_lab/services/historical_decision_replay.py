from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from red_bar_lab.execution.candidate_lifecycle import CandidateLifecycleManager, MarketSessionManager
from red_bar_lab.execution.automation import CandidateScore
from red_bar_lab.execution.paper_engine import PaperContract
from red_bar_lab.execution.opportunity_engine import OpportunityIntelligenceEngine
from red_bar_lab.execution.performance_selection import PerformanceTradeSelectionEngine
from red_bar_lab.execution.institutional_execution import InstitutionalExecutionCommittee
from red_bar_lab.execution.portfolio_manager import PortfolioCandidate, PortfolioRiskManager
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.strategy.identity import canonical_signal_id
from red_bar_lab.strategy.level_engine import build_daily_levels
from red_bar_lab.strategy.models import Direction, SignalState
from red_bar_lab.strategy.signal_engine import scan_reference_levels
from red_bar_lab.strategy.trade_engine import evaluate_active_signals

IST = "Asia/Kolkata"


@dataclass(frozen=True)
class DecisionReplayRow:
    signal_id: str
    timestamp: str
    level_type: str
    direction: str
    option_side: str
    lifecycle_state: str
    lifecycle_action: str
    market_session: str
    primary_confidence_pct: float
    shadow_decision: str
    shadow_confidence_pct: float
    agreement: str
    shadow_adjustment_pct: float
    final_confidence_pct: float
    expectancy_pct: float
    decision: str
    execution: str
    blocker: str
    data_fidelity: str
    vwap_ok: bool | None
    ema_ok: bool | None
    momentum_ok: bool | None
    volume_score: float
    oi_score: float
    outcome_points: float | None
    outcome_result: str
    verdict: str
    learning_attribution: str
    learning_recommendation: str
    candidate_symbol: str | None = None
    candidate_rank: int | None = None
    candidate_score: float | None = None
    opportunity_health: float | None = None
    portfolio_status: str | None = None
    portfolio_reason: str | None = None
    exit_reason: str | None = None
    option_entry_price: float | None = None
    option_exit_price: float | None = None
    option_return_pct: float | None = None
    outcome_basis: str = "UNRESOLVED"

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class HistoricalDecisionReplayResult:
    trading_date: date
    rows: tuple[DecisionReplayRow, ...]
    active_signals: int
    approved: int
    blocked: int
    waiting: int
    expired: int
    winners: int
    losers: int
    net_points: float
    data_fidelity: str
    correct_takes: int
    false_positives: int
    missed_opportunities: int
    correct_skips: int
    incorrect_blocks: int
    correct_blocks: int
    decision_accuracy_pct: float
    learning_recommendations: tuple[str, ...]
    option_contract_coverage_pct: float = 0.0
    option_candle_coverage_pct: float = 0.0
    option_oi_coverage_pct: float = 0.0
    replay_ready: bool = True
    replay_fidelity_reason: str = ""
    portfolio_admitted: int = 0
    portfolio_watchlisted: int = 0
    data_source: str = "UNKNOWN"


class HistoricalDecisionReplayService:
    """Point-in-time decision validation using cached one-minute candles.

    This harness intentionally never reads future candles while constructing a
    decision. Future rows are consulted only after the decision to label the
    eventual underlying outcome. Option-only live inputs that were not captured
    intraday (bid/ask depth, intraday option candles, Greeks) remain neutral and
    are surfaced as a replay fidelity limitation rather than fabricated.
    """

    def __init__(
        self,
        historical,
        *,
        freshness_seconds: int = 180,
        hard_expiry_seconds: int = 900,
        minimum_confidence_pct: float = 70.0,
        stop_loss_pct: float = 15.0,
        target_pct: float = 25.0,
        option_chain_sync=None,
        initial_capital: float = 100000.0,
        minimum_opportunity_health: float = 75.0,
        maximum_open_trades: int = 5,
        maximum_same_direction_trades: int = 3,
        maximum_portfolio_capital_pct: float = 40.0,
        maximum_portfolio_risk_pct: float = 2.0,
    ) -> None:
        self.historical = historical
        self.option_chain_sync = option_chain_sync
        self.initial_capital = float(initial_capital)
        self.lifecycle = CandidateLifecycleManager(
            freshness_seconds=freshness_seconds,
            hard_expiry_seconds=hard_expiry_seconds,
        )
        self.minimum_confidence_pct = float(minimum_confidence_pct)
        self.stop_loss_pct = float(stop_loss_pct)
        self.target_pct = float(target_pct)
        self.opportunity_engine = OpportunityIntelligenceEngine(minimum_opportunity_score=float(minimum_opportunity_health))
        self.selection_engine = PerformanceTradeSelectionEngine()
        self.execution_committee = InstitutionalExecutionCommittee(
            minimum_execution_probability_pct=float(minimum_confidence_pct),
            minimum_expected_value_pct=0.0,
        )
        self.portfolio_manager = PortfolioRiskManager(
            maximum_open_trades=maximum_open_trades,
            maximum_same_direction=maximum_same_direction_trades,
            maximum_capital_pct=maximum_portfolio_capital_pct,
            maximum_risk_pct=maximum_portfolio_risk_pct,
            minimum_opportunity_health=minimum_opportunity_health,
        )
        self.exit_engine = PaperExitEngine()

    @staticmethod
    def _to_ist(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        ts = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
        result = result.loc[ts.notna()].copy()
        result["timestamp"] = ts.loc[ts.notna()].dt.tz_convert(IST)
        return result.sort_values("timestamp").reset_index(drop=True)

    @staticmethod
    def _point_in_time_metrics(frame: pd.DataFrame, moment, direction: str) -> dict[str, object]:
        work = HistoricalDecisionReplayService._to_ist(frame)
        ts = pd.Timestamp(moment)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        work = work.loc[work["timestamp"] <= ts].copy()
        if work.empty:
            return {
                "vwap_ok": None, "ema_ok": None, "momentum_ok": None,
                "volume_score": 7.5, "oi_score": 5.0,
            }

        close = pd.to_numeric(work["close"], errors="coerce")
        volume = pd.to_numeric(work.get("volume", 0.0), errors="coerce").fillna(0.0)
        latest_close = float(close.iloc[-1])

        if float(volume.sum()) > 0:
            typical = (
                pd.to_numeric(work["high"], errors="coerce")
                + pd.to_numeric(work["low"], errors="coerce")
                + close
            ) / 3.0
            vwap = float((typical * volume).sum() / volume.sum())
            vwap_ok = latest_close >= vwap if direction == "BULLISH" else latest_close <= vwap
            recent_avg = float(volume.tail(20).mean()) if len(volume) else 0.0
            rel = float(volume.iloc[-1]) / recent_avg if recent_avg > 0 else 1.0
            volume_score = max(0.0, min(15.0, 7.5 * rel))
        else:
            vwap_ok = None
            volume_score = 7.5

        ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema_ok = ema9 >= ema21 if direction == "BULLISH" else ema9 <= ema21

        lookback = min(5, max(1, len(close) - 1))
        if len(close) >= 2:
            prev = float(close.iloc[-1 - lookback])
            momentum_pct = ((latest_close - prev) / prev * 100.0) if prev else 0.0
            momentum_ok = momentum_pct >= 0 if direction == "BULLISH" else momentum_pct <= 0
        else:
            momentum_ok = None

        oi_score = 5.0
        if "oi" in work.columns:
            oi = pd.to_numeric(work["oi"], errors="coerce").dropna()
            if not oi.empty and float(oi.max()) > 0:
                oi_score = min(10.0, max(0.0, float(oi.iloc[-1]) / max(float(oi.max()), 1.0) * 10.0))

        return {
            "vwap_ok": vwap_ok,
            "ema_ok": ema_ok,
            "momentum_ok": momentum_ok,
            "volume_score": round(volume_score, 2),
            "oi_score": round(oi_score, 2),
        }

    @staticmethod
    def _score(metrics: dict[str, object]) -> float:
        # Historical replay cannot reconstruct live bid/ask depth unless it was
        # captured. Use neutral priors for spread/liquidity; never pretend PASS.
        spread = 7.5
        liquidity = 10.0
        volume = float(metrics["volume_score"])
        oi = float(metrics["oi_score"])
        vwap = 5.0 if metrics["vwap_ok"] is None else (10.0 if metrics["vwap_ok"] else 0.0)
        ema = 5.0 if metrics["ema_ok"] is None else (10.0 if metrics["ema_ok"] else 0.0)
        momentum = 5.0 if metrics["momentum_ok"] is None else (10.0 if metrics["momentum_ok"] else 0.0)
        return round((spread + liquidity + volume + oi + vwap + ema + momentum) / 90.0 * 100.0, 2)


    @staticmethod
    def _historical_candidate(contract_row: dict[str, object], candles: pd.DataFrame) -> CandidateScore | None:
        if candles is None or candles.empty:
            return None
        work = candles.copy()
        close = pd.to_numeric(work.get("close"), errors="coerce")
        if close.empty or close.dropna().empty:
            return None
        volume = pd.to_numeric(work.get("volume", 0.0), errors="coerce").fillna(0.0)
        oi = pd.to_numeric(work.get("oi", 0.0), errors="coerce").fillna(0.0)
        typical = (pd.to_numeric(work.get("high"), errors="coerce") + pd.to_numeric(work.get("low"), errors="coerce") + close) / 3.0
        cumulative_volume = volume.cumsum()
        vwap_series = (typical * volume).cumsum() / cumulative_volume.replace(0, pd.NA)
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        latest_close = float(close.iloc[-1])
        latest_vwap = float(vwap_series.iloc[-1]) if pd.notna(vwap_series.iloc[-1]) else latest_close
        latest_ema9 = float(ema9.iloc[-1])
        latest_ema21 = float(ema21.iloc[-1])
        lookback = min(5, max(1, len(close) - 1))
        momentum_pct = None
        momentum_score = 0.0
        if len(close) >= 2:
            previous = float(close.iloc[-1 - lookback])
            momentum_pct = ((latest_close - previous) / previous * 100.0) if previous else 0.0
            momentum_score = (10.0 if momentum_pct >= 0.75 else 8.0 if momentum_pct >= 0.35 else
                              6.0 if momentum_pct >= 0.10 else 4.0 if momentum_pct >= 0.0 else
                              2.0 if momentum_pct >= -0.25 else 0.0)
        # Same-day live-capture replay can preserve the actual bid/ask and
        # quantities from the captured option-chain snapshots. Expired-option
        # candle replay does not have these fields, so it keeps neutral priors.
        bid = float(pd.to_numeric(work.get("best_bid", pd.Series([0.0]*len(work))), errors="coerce").fillna(0.0).iloc[-1]) if len(work) else 0.0
        ask = float(pd.to_numeric(work.get("best_ask", pd.Series([0.0]*len(work))), errors="coerce").fillna(0.0).iloc[-1]) if len(work) else 0.0
        buy_qty = float(pd.to_numeric(work.get("best_bid_qty", pd.Series([0.0]*len(work))), errors="coerce").fillna(0.0).iloc[-1]) if len(work) else 0.0
        sell_qty = float(pd.to_numeric(work.get("best_ask_qty", pd.Series([0.0]*len(work))), errors="coerce").fillna(0.0).iloc[-1]) if len(work) else 0.0
        lot_hint = int(float(contract_row.get("lot_size") or contract_row.get("minimum_lot") or 75))
        if latest_close > 0 and ask > 0 and bid > 0 and ask >= bid:
            spread_pct = (ask - bid) / latest_close * 100.0
            spread_score = (15.0 if spread_pct <= 0.5 else 12.0 if spread_pct <= 1.0 else
                            8.0 if spread_pct <= 2.0 else 3.0 if spread_pct <= 4.0 else 0.0)
            liquidity_score = (20.0 if min(buy_qty, sell_qty) >= lot_hint * 5 else
                               15.0 if min(buy_qty, sell_qty) >= lot_hint * 2 else
                               10.0 if min(buy_qty, sell_qty) >= lot_hint else
                               5.0 if buy_qty > 0 and sell_qty > 0 else 0.0)
            source_reason = "LIVE_CAPTURE_POINT_IN_TIME"
        else:
            spread_score, liquidity_score = 7.5, 10.0
            source_reason = "HISTORICAL_OPTION_CANDLES; bid/ask depth unavailable-neutral"
        latest_volume = float(volume.iloc[-1]) if len(volume) else 0.0
        latest_oi = float(oi.iloc[-1]) if len(oi) else 0.0
        volume_score = min(15.0, latest_volume / 50000.0 * 15.0)
        oi_score = min(10.0, latest_oi / 100000.0 * 10.0)
        vwap_score = 10.0 if latest_close >= latest_vwap else 0.0
        ema_score = 10.0 if latest_ema9 >= latest_ema21 else 0.0
        raw = spread_score + liquidity_score + volume_score + oi_score + vwap_score + ema_score + momentum_score
        total = raw / 90.0 * 100.0
        symbol = str(contract_row.get("trading_symbol") or contract_row.get("tradingsymbol") or contract_row.get("symbol") or "HIST_OPTION")
        typraw = str(contract_row.get("instrument_type") or contract_row.get("option_type") or "").upper()
        option_type = "CE" if ("CE" in typraw or "CALL" in typraw or symbol.upper().endswith("CE")) else "PE"
        strike = float(contract_row.get("strike_price") or contract_row.get("strike") or 0.0)
        expiry_raw = str(contract_row.get("expiry") or contract_row.get("expiry_date") or date.today().isoformat())[:10]
        try: expiry = date.fromisoformat(expiry_raw)
        except ValueError: expiry = date.today()
        lot = int(float(contract_row.get("lot_size") or contract_row.get("minimum_lot") or 75))
        token = abs(hash(str(contract_row.get("instrument_key") or symbol))) % 2_000_000_000
        contract = PaperContract(token, symbol, "NSE", option_type, strike, expiry, max(1, lot))
        return CandidateScore(contract, round(total,2), spread_score, liquidity_score, round(volume_score,2),
                              round(oi_score,2), vwap_score, ema_score, momentum_score,
                              round(momentum_pct,4) if momentum_pct is not None else None,
                              len(work), latest_close, bid or None, ask or None, source_reason)

    @staticmethod
    def _option_features(candles: pd.DataFrame, upto_index: int) -> dict[str, object]:
        work = candles.iloc[: upto_index + 1].copy()
        close = pd.to_numeric(work["close"], errors="coerce")
        volume = pd.to_numeric(work.get("volume", 0.0), errors="coerce").fillna(0.0)
        typical = (pd.to_numeric(work["high"], errors="coerce") + pd.to_numeric(work["low"], errors="coerce") + close) / 3.0
        denom = float(volume.sum())
        vwap = float((typical * volume).sum() / denom) if denom > 0 else float(close.iloc[-1])
        ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        lookback = min(5, max(1, len(close)-1))
        momentum = 0.0
        if len(close) >= 2:
            prev=float(close.iloc[-1-lookback]); momentum=((float(close.iloc[-1])-prev)/prev*100.0) if prev else 0.0
        avg=float(volume.tail(20).mean()) if len(volume) else 0.0
        rv=float(volume.iloc[-1])/avg if avg>0 else None
        return {"close":float(close.iloc[-1]),"vwap":vwap,"ema9":ema9,"ema21":ema21,"momentum_pct":momentum,"relative_volume":rv}

    def _simulate_exit(self, *, candidate: CandidateScore, all_candles: pd.DataFrame, entry_moment,
                       signal: dict[str, object], underlying: pd.DataFrame) -> dict[str, object]:
        frame = all_candles.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
        entry_ts = pd.Timestamp(entry_moment)
        if entry_ts.tzinfo is None: entry_ts = entry_ts.tz_localize(IST)
        entry_utc = entry_ts.tz_convert("UTC")
        future = frame.loc[frame["timestamp"] >= entry_utc].reset_index(drop=True)
        if future.empty:
            return {"exit_time": None, "entry": candidate.ltp, "exit": None, "return_pct": None, "reason":"NO_FUTURE_OPTION_CANDLES"}
        entry = float(future.iloc[0]["close"])
        position={"entry_price":entry,"current_price":entry,"initial_stop_price":entry*(1-self.stop_loss_pct/100.0),
                  "stop_price":entry*(1-self.stop_loss_pct/100.0),"target1_price":entry*(1+self.target_pct/100.0),
                  "target2_price":None,"mfe_points":0.0}
        peak=entry
        u=HistoricalDecisionReplayService._to_ist(underlying)
        for idx,row in future.iterrows():
            current=float(row["close"]); peak=max(peak,current); position["current_price"]=current; position["mfe_points"]=peak-entry
            local_ts=pd.Timestamp(row["timestamp"]).tz_convert(IST)
            prior_u=u.loc[u["timestamp"]<=local_ts]
            underlying_price=float(prior_u.iloc[-1]["close"]) if not prior_u.empty else None
            features=self._option_features(future, idx)
            eod_due=local_ts.time() >= pd.Timestamp("15:25").time()
            health=self.exit_engine.evaluate(position=position, option_candle=features, signal=signal,
                current_underlying=underlying_price, opposite_red_bar_confirmed=False, eod_due=eod_due)
            if health.action=="EXIT":
                return {"exit_time":local_ts,"entry":entry,"exit":current,
                        "return_pct":round((current-entry)/entry*100.0,3) if entry else None,
                        "reason":health.hard_exit_reason or "HEALTH_EXIT"}
        last=float(future.iloc[-1]["close"])
        return {"exit_time":pd.Timestamp(future.iloc[-1]["timestamp"]).tz_convert(IST),"entry":entry,"exit":last,
                "return_pct":round((last-entry)/entry*100.0,3) if entry else None,"reason":"EOD_DATA_END"}



    @staticmethod
    def _verdict(execution: str, outcome_result: str) -> str:
        if outcome_result not in {"WIN", "LOSS", "BREAKEVEN"}:
            return "UNRESOLVED"
        if outcome_result == "BREAKEVEN":
            return "NEUTRAL"
        if execution == "WOULD_TAKE":
            return "CORRECT_TAKE" if outcome_result == "WIN" else "FALSE_POSITIVE"
        if execution == "WOULD_WAIT":
            return "MISSED_OPPORTUNITY" if outcome_result == "WIN" else "CORRECT_SKIP"
        if execution == "WOULD_BLOCK":
            return "INCORRECT_BLOCK" if outcome_result == "WIN" else "CORRECT_BLOCK"
        return "UNRESOLVED"

    @staticmethod
    def _learning_attribution(
        *, verdict: str, blocker: str, shadow_decision: str, shadow_adjustment: float,
        vwap_ok: bool | None, ema_ok: bool | None, momentum_ok: bool | None,
    ) -> tuple[str, str]:
        if verdict == "MISSED_OPPORTUNITY":
            if blocker.startswith("FINAL_CONFIDENCE"):
                return (
                    "CONFIDENCE_THRESHOLD",
                    "Review the minimum confidence threshold against a larger replay sample; this profitable setup fell below it.",
                )
            if vwap_ok is None:
                return (
                    "MISSING_VWAP_EVIDENCE",
                    "Historical VWAP evidence was unavailable/neutral. Improve replay data coverage before increasing live authority.",
                )
            return ("COMMITTEE_TOO_CONSERVATIVE", "Review the blocking evidence on a larger replay sample; this setup later won.")
        if verdict == "FALSE_POSITIVE":
            weak=[]
            if vwap_ok is False: weak.append("VWAP")
            if ema_ok is False: weak.append("EMA")
            if momentum_ok is False: weak.append("MOMENTUM")
            suffix = ", ".join(weak) if weak else "no obvious technical disagreement"
            return (
                "COMMITTEE_TOO_PERMISSIVE",
                f"Review positive-decision evidence ({suffix}); this taken setup later lost. Do not auto-tighten live thresholds from one replay.",
            )
        if verdict == "INCORRECT_BLOCK":
            return (
                "HARD_BLOCK_REVIEW",
                "Audit this hard blocker: the blocked setup later won. Preserve safety unless repeated replay evidence proves the blocker is overly broad.",
            )
        if verdict == "CORRECT_SKIP":
            return ("CONSERVATIVE_FILTER_WORKED", "No change suggested; WAIT avoided a losing setup.")
        if verdict == "CORRECT_BLOCK":
            return ("HARD_BLOCK_WORKED", "No change suggested; the hard blocker avoided a losing setup.")
        if verdict == "CORRECT_TAKE":
            return ("DECISION_ALIGNED", "No change suggested; the engine took a setup that later won.")
        return ("NO_LEARNING_LABEL", "No parameter recommendation from an unresolved/breakeven outcome.")

    @staticmethod
    def _aggregate_learning(rows: list[DecisionReplayRow]) -> tuple[tuple[str, ...], float]:
        resolved=[r for r in rows if r.verdict not in {"UNRESOLVED", "NEUTRAL"}]
        if not resolved:
            return ((), 0.0)
        correct=sum(r.verdict in {"CORRECT_TAKE","CORRECT_SKIP","CORRECT_BLOCK"} for r in resolved)
        accuracy=round(correct/len(resolved)*100.0,2)
        missed=[r for r in resolved if r.verdict=="MISSED_OPPORTUNITY"]
        false_pos=[r for r in resolved if r.verdict=="FALSE_POSITIVE"]
        bad_blocks=[r for r in resolved if r.verdict=="INCORRECT_BLOCK"]
        recs=[]
        if missed:
            recs.append(
                f"Confidence calibration: {len(missed)} profitable setup(s) were skipped. Compare their Final % distribution with correct skips before changing MIN confidence."
            )
        if false_pos:
            recs.append(
                f"False-positive review: {len(false_pos)} taken setup(s) lost. Inspect VWAP/EMA/Momentum disagreement before loosening any entry thresholds."
            )
        if bad_blocks:
            recs.append(
                f"Hard-block audit: {len(bad_blocks)} blocked setup(s) later won. Audit blocker scope, but keep safety gates unchanged until repeated evidence supports a change."
            )
        if not recs:
            recs.append("No adverse decision pattern detected in this replay day; keep current live parameters unchanged.")
        return tuple(recs), accuracy

    @staticmethod
    def _outcome_map(frame: pd.DataFrame, attempts: Iterable, instrument_key: str, trading_date: date):
        # EOD hold is used only as an outcome label after the decision timestamp.
        outcomes = evaluate_active_signals(
            frame, attempts, instrument_key=instrument_key,
            trading_date=trading_date.isoformat(),
        )
        result = {}
        for item in outcomes:
            if str(getattr(item.exit_model, "value", item.exit_model)) != "EOD_HOLD":
                continue
            result[item.signal_id] = item
        return result

    def _run_live_parity_day(self, instrument_key: str, trading_date: date, coverage) -> HistoricalDecisionReplayResult:
        current = self.historical.read_day(instrument_key, trading_date, interval_minutes=1)
        if current.empty:
            raise ValueError(f"No cached 1-minute candles for {trading_date.isoformat()}")
        prior_dates = [d for d in self.historical.available_dates(instrument_key, interval_minutes=1) if d < trading_date][-10:]
        previous = [(d, self.historical.read_day(instrument_key, d, interval_minutes=1)) for d in prior_dates]
        daily = build_daily_levels(trading_date, current, previous, previous_days=10)
        levels = list(daily.previous_day_levels)
        levels.extend(x for x in (daily.first_candle, daily.next_red_candle, daily.mid_session_candle) if x is not None)
        scan = scan_reference_levels(current, levels)
        active = [x for x in scan.active if x.confirmation_timestamp is not None and x.direction is not None]
        active.sort(key=lambda x: pd.Timestamp(x.confirmation_timestamp))

        rows: list[DecisionReplayRow] = []
        scheduled_positions: list[dict[str, object]] = []
        admitted_total = watch_total = 0
        for attempt in active:
            direction = attempt.direction.value
            side = "CE" if direction == "BULLISH" else "PE"
            signal_id = canonical_signal_id(
                instrument_key, trading_date.isoformat(), attempt.level_type, direction,
                attempt.cross_timestamp.isoformat() if attempt.cross_timestamp else None,
                attempt.confirmation_timestamp.isoformat() if attempt.confirmation_timestamp else None,
            )
            moment = pd.Timestamp(attempt.confirmation_timestamp).to_pydatetime()
            moment_ts = pd.Timestamp(moment)
            if moment_ts.tzinfo is None: moment_ts = moment_ts.tz_localize(IST)
            scheduled_positions = [p for p in scheduled_positions if p.get("exit_time") is None or pd.Timestamp(p["exit_time"]) > moment_ts]
            open_count=len(scheduled_positions)
            current_ce=sum(p.get("option_type")=="CE" for p in scheduled_positions)
            current_pe=sum(p.get("option_type")=="PE" for p in scheduled_positions)
            deployed=sum(float(p.get("capital") or 0.0) for p in scheduled_positions)
            risk=sum(float(p.get("risk") or 0.0) for p in scheduled_positions)

            u = self._to_ist(current)
            prior_u=u.loc[u["timestamp"]<=moment_ts]
            spot=float(prior_u.iloc[-1]["close"]) if not prior_u.empty else float(attempt.underlying_entry or 0.0)
            signal={"signal_id":signal_id,"direction":direction,"confirmation_high":attempt.confirmation_high,
                    "confirmation_low":attempt.confirmation_low,"confirmation_close":attempt.confirmation_close,
                    "underlying_entry":attempt.underlying_entry}
            contract_frames=self.option_chain_sync.point_in_time_contracts(instrument_key,trading_date,moment)
            scored=[]
            full_frame_by_symbol={}
            for raw, prior in contract_frames:
                candidate=self._historical_candidate(raw, prior)
                if candidate is None or candidate.contract.option_type != side:
                    continue
                scored.append(candidate)
                full_frame_by_symbol[candidate.contract.tradingsymbol]=self.option_chain_sync.full_contract_candles(
                    instrument_key, trading_date, raw
                )
            scored.sort(key=lambda c:(c.total_score,-abs(c.contract.strike-spot)),reverse=True)
            scored=scored[:5]
            metrics=self._point_in_time_metrics(current,moment,direction)
            session=MarketSessionManager.classify(moment)
            lifecycle=self.lifecycle.evaluate(signal_id=signal_id,confirmation_timestamp=attempt.confirmation_timestamp.isoformat(),now=moment)

            evals=[]
            for rank,candidate in enumerate(scored,1):
                age=0.0
                opportunity=self.opportunity_engine.evaluate(signal=signal,candidate=candidate,spot_price=spot,
                    signal_age_seconds=age,opposite_red_bar_confirmed=False,freshness_seconds=180.0)
                selection=self.selection_engine.evaluate(candidate=candidate,candidate_rank=rank,opportunity=opportunity,
                    historical_orders=(),entry_mode=opportunity.entry_mode,minimum_candidate_score=65.0,
                    stop_loss_pct=self.stop_loss_pct,target_pct=self.target_pct,require_opportunity_gate=False)
                committee=self.execution_committee.evaluate(candidate=candidate,selection=selection,opportunity=opportunity,
                    historical_orders=(),current_shadow=None,historical_shadow=(),stop_loss_pct=self.stop_loss_pct,target_pct=self.target_pct)
                evals.append((committee,selection,candidate,opportunity))

            pcandidates=[]
            for comm,sel,cand,opp in evals:
                if not comm.eligible: continue
                ref=float(cand.ltp or 0.0)
                pcandidates.append(PortfolioCandidate(
                    queue_id=f"H-{signal_id}-{cand.contract.instrument_token}",signal_id=signal_id,symbol=cand.contract.tradingsymbol,
                    option_type=cand.contract.option_type,rank=sel.candidate_rank,candidate_score=cand.total_score,
                    opportunity_health=opp.opportunity_score,expectancy_pct=comm.expected_value_pct,reference_price=ref,
                    stop_loss_pct=self.stop_loss_pct,quantity=cand.contract.lot_size,
                ))
            admissions=self.portfolio_manager.admit(pcandidates,initial_capital=self.initial_capital,current_open_trades=open_count,
                current_deployed_capital=deployed,current_risk=risk,current_ce=current_ce,current_pe=current_pe)
            by_queue={a.queue_id:a for a in admissions}

            if not evals:
                outcome_result="UNKNOWN"
                verdict=self._verdict("WOULD_WAIT",outcome_result)
                rows.append(DecisionReplayRow(signal_id,pd.Timestamp(attempt.confirmation_timestamp).isoformat(),attempt.level_type,direction,side,
                    lifecycle.state,lifecycle.action,session.code,0.0,"WAIT",50.0,"INFORMATIONAL",0.0,0.0,0.0,"WAIT","WOULD_WAIT",
                    "NO_OPTION_CANDIDATES_AT_TIMESTAMP",coverage.fidelity,metrics["vwap_ok"],metrics["ema_ok"],metrics["momentum_ok"],
                    float(metrics["volume_score"]),float(metrics["oi_score"]),None,outcome_result,verdict,"OPTION_DATA_GAP",
                    "No point-in-time option candidates were available; improve historical option coverage."))
                continue

            for comm,sel,cand,opp in evals:
                queue_id=f"H-{signal_id}-{cand.contract.instrument_token}"
                admission=by_queue.get(queue_id)
                execution="WOULD_WAIT"; decision="WAIT"; blocker=comm.reason
                portfolio_status="NOT_QUALIFIED"; portfolio_reason=comm.reason
                exit_info={"exit_time":None,"entry":cand.ltp,"exit":None,"return_pct":None,"reason":None}
                if not session.entry_allowed:
                    execution="WOULD_BLOCK"; decision="BLOCKED"; blocker=f"MARKET_SESSION_{session.code}"; portfolio_status="BLOCKED"; portfolio_reason=blocker
                elif comm.eligible and admission and admission.admitted:
                    execution="WOULD_TAKE"; decision="APPROVED"; blocker="NONE"; portfolio_status="APPROVED"; portfolio_reason=admission.reason
                    admitted_total+=1
                elif comm.eligible and admission:
                    execution="WOULD_WAIT"; decision="WAIT"; blocker=admission.reason; portfolio_status="WATCHLIST"; portfolio_reason=admission.reason; watch_total+=1

                # Freeze the historical decision above. Only now may future option candles
                # be consumed to label the factual/counterfactual outcome for research.
                full=full_frame_by_symbol.get(cand.contract.tradingsymbol,pd.DataFrame())
                if not full.empty:
                    exit_info=self._simulate_exit(candidate=cand,all_candles=full,entry_moment=moment,signal=signal,underlying=current)
                if execution=="WOULD_TAKE":
                    capital=float(exit_info.get("entry") or cand.ltp or 0.0)*cand.contract.lot_size
                    scheduled_positions.append({"exit_time":exit_info.get("exit_time"),"option_type":side,"capital":capital,"risk":capital*self.stop_loss_pct/100.0})
                points=None
                ret=exit_info.get("return_pct")
                if ret is not None:
                    points=float((exit_info.get("exit") or 0.0)-(exit_info.get("entry") or 0.0))
                    outcome_result="WIN" if ret>0 else "LOSS" if ret<0 else "BREAKEVEN"
                else:
                    outcome_result="UNKNOWN"
                verdict=self._verdict(execution,outcome_result)
                attribution,recommendation=self._learning_attribution(verdict=verdict,blocker=blocker,shadow_decision="WAIT",shadow_adjustment=0.0,
                    vwap_ok=metrics["vwap_ok"],ema_ok=metrics["ema_ok"],momentum_ok=metrics["momentum_ok"])
                rows.append(DecisionReplayRow(
                    signal_id=signal_id,timestamp=pd.Timestamp(attempt.confirmation_timestamp).isoformat(),level_type=attempt.level_type,
                    direction=direction,option_side=side,lifecycle_state=lifecycle.state,lifecycle_action=lifecycle.action,market_session=session.code,
                    primary_confidence_pct=comm.primary_confidence_pct,shadow_decision="WAIT",shadow_confidence_pct=50.0,agreement="INFORMATIONAL",
                    shadow_adjustment_pct=0.0,final_confidence_pct=comm.execution_probability_pct,expectancy_pct=comm.expected_value_pct,
                    decision=decision,execution=execution,blocker=blocker,data_fidelity=coverage.fidelity,vwap_ok=metrics["vwap_ok"],
                    ema_ok=metrics["ema_ok"],momentum_ok=metrics["momentum_ok"],volume_score=cand.volume_score,oi_score=cand.oi_score,
                    outcome_points=points,outcome_result=outcome_result,verdict=verdict,learning_attribution=attribution,
                    learning_recommendation=recommendation,candidate_symbol=cand.contract.tradingsymbol,candidate_rank=sel.candidate_rank,
                    candidate_score=cand.total_score,opportunity_health=opp.opportunity_score,portfolio_status=portfolio_status,
                    portfolio_reason=portfolio_reason,exit_reason=exit_info.get("reason"),option_entry_price=exit_info.get("entry"),
                    option_exit_price=exit_info.get("exit"),option_return_pct=ret,
                    outcome_basis="EXECUTED_EXIT_ENGINE" if execution=="WOULD_TAKE" else "COUNTERFACTUAL_EXIT_ENGINE",
                ))

        approved=sum(r.execution=="WOULD_TAKE" for r in rows); blocked=sum(r.execution=="WOULD_BLOCK" for r in rows); waiting=sum(r.execution=="WOULD_WAIT" for r in rows)
        winners=sum(r.execution=="WOULD_TAKE" and r.outcome_result=="WIN" for r in rows); losers=sum(r.execution=="WOULD_TAKE" and r.outcome_result=="LOSS" for r in rows)
        net=sum((r.outcome_points or 0.0) for r in rows if r.execution=="WOULD_TAKE")
        recs,accuracy=self._aggregate_learning(rows)
        return HistoricalDecisionReplayResult(trading_date,tuple(rows),len(active),approved,blocked,waiting,0,winners,losers,round(net,2),coverage.fidelity,
            sum(r.verdict=="CORRECT_TAKE" for r in rows),sum(r.verdict=="FALSE_POSITIVE" for r in rows),
            sum(r.verdict=="MISSED_OPPORTUNITY" for r in rows),sum(r.verdict=="CORRECT_SKIP" for r in rows),
            sum(r.verdict=="INCORRECT_BLOCK" for r in rows),sum(r.verdict=="CORRECT_BLOCK" for r in rows),accuracy,recs,
            coverage.contract_coverage_pct,coverage.candle_coverage_pct,coverage.oi_coverage_pct,coverage.replay_ready,coverage.reason,
            admitted_total,watch_total,coverage.data_source)

    def run_day(self, instrument_key: str, trading_date: date) -> HistoricalDecisionReplayResult:
        if self.option_chain_sync is not None:
            coverage = self.option_chain_sync.validate_day(instrument_key, trading_date)
            if not coverage.replay_ready:
                raise ValueError(
                    f"Historical option replay is not ready for {trading_date.isoformat()}: "
                    f"{coverage.fidelity}; contract coverage={coverage.contract_coverage_pct:.1f}%, "
                    f"candle coverage={coverage.candle_coverage_pct:.1f}%. "
                    "Run Sync / Repair Historical Option Chain first."
                )
            return self._run_live_parity_day(instrument_key, trading_date, coverage)
        current = self.historical.read_day(instrument_key, trading_date, interval_minutes=1)
        if current.empty:
            raise ValueError(f"No cached 1-minute candles for {trading_date.isoformat()}")

        prior_dates = [
            d for d in self.historical.available_dates(instrument_key, interval_minutes=1)
            if d < trading_date
        ][-10:]
        previous = [(d, self.historical.read_day(instrument_key, d, interval_minutes=1)) for d in prior_dates]
        daily = build_daily_levels(trading_date, current, previous, previous_days=10)
        levels = list(daily.previous_day_levels)
        levels.extend(x for x in (daily.first_candle, daily.next_red_candle, daily.mid_session_candle) if x is not None)
        scan = scan_reference_levels(current, levels)
        active = [x for x in scan.active if x.confirmation_timestamp is not None and x.direction is not None]
        outcomes = self._outcome_map(current, active, instrument_key, trading_date)

        rows: list[DecisionReplayRow] = []
        for attempt in active:
            direction = attempt.direction.value
            signal_id = canonical_signal_id(
                instrument_key, trading_date.isoformat(), attempt.level_type, direction,
                attempt.cross_timestamp.isoformat() if attempt.cross_timestamp else None,
                attempt.confirmation_timestamp.isoformat() if attempt.confirmation_timestamp else None,
            )
            moment = pd.Timestamp(attempt.confirmation_timestamp).to_pydatetime()
            metrics = self._point_in_time_metrics(current, moment, direction)
            primary = self._score(metrics)

            # Shadow is informational-only in RB-1.4.1. Historical replay still
            # records the advisory view, but it never changes the Primary decision.
            shadow_decision = "WAIT"
            shadow_conf = 50.0
            agreement = "INFORMATIONAL"
            shadow_adjustment = 0.0
            final_conf = round(primary, 2)
            expectancy = round(
                (final_conf / 100.0) * self.target_pct
                - (1.0 - final_conf / 100.0) * self.stop_loss_pct,
                3,
            )

            lifecycle = self.lifecycle.evaluate(
                signal_id=signal_id,
                confirmation_timestamp=attempt.confirmation_timestamp.isoformat(),
                now=moment,
            )
            session = MarketSessionManager.classify(moment)

            blocker = "NONE"
            decision = "APPROVED"
            execution = "WOULD_TAKE"
            if not session.entry_allowed:
                blocker = f"MARKET_SESSION_{session.code}"
                decision = "BLOCKED"
                execution = "WOULD_BLOCK"
            elif final_conf < self.minimum_confidence_pct:
                blocker = f"FINAL_CONFIDENCE={final_conf:.2f}<MIN={self.minimum_confidence_pct:.2f}"
                decision = "WAIT"
                execution = "WOULD_WAIT"
            elif expectancy <= 0:
                blocker = f"EXPECTANCY={expectancy:.3f}<=0"
                decision = "WAIT"
                execution = "WOULD_WAIT"

            outcome = outcomes.get(signal_id)
            points = float(outcome.points) if outcome is not None and outcome.points is not None else None
            outcome_result = "UNKNOWN"
            if points is not None:
                outcome_result = "WIN" if points > 0 else "LOSS" if points < 0 else "BREAKEVEN"

            verdict = self._verdict(execution, outcome_result)
            attribution, recommendation = self._learning_attribution(
                verdict=verdict, blocker=blocker, shadow_decision=shadow_decision,
                shadow_adjustment=shadow_adjustment, vwap_ok=metrics["vwap_ok"],
                ema_ok=metrics["ema_ok"], momentum_ok=metrics["momentum_ok"],
            )

            rows.append(DecisionReplayRow(
                signal_id=signal_id,
                timestamp=pd.Timestamp(attempt.confirmation_timestamp).isoformat(),
                level_type=attempt.level_type,
                direction=direction,
                option_side="CE" if direction == "BULLISH" else "PE",
                lifecycle_state=lifecycle.state,
                lifecycle_action=lifecycle.action,
                market_session=session.code,
                primary_confidence_pct=primary,
                shadow_decision=shadow_decision,
                shadow_confidence_pct=shadow_conf,
                agreement=agreement,
                shadow_adjustment_pct=shadow_adjustment,
                final_confidence_pct=final_conf,
                expectancy_pct=expectancy,
                decision=decision,
                execution=execution,
                blocker=blocker,
                data_fidelity="POINT_IN_TIME_UNDERLYING; OPTION_MICROSTRUCTURE_UNAVAILABLE_NEUTRAL",
                vwap_ok=metrics["vwap_ok"],
                ema_ok=metrics["ema_ok"],
                momentum_ok=metrics["momentum_ok"],
                volume_score=float(metrics["volume_score"]),
                oi_score=float(metrics["oi_score"]),
                outcome_points=points,
                outcome_result=outcome_result,
                verdict=verdict,
                learning_attribution=attribution,
                learning_recommendation=recommendation,
            ))

        approved = sum(r.execution == "WOULD_TAKE" for r in rows)
        blocked = sum(r.execution == "WOULD_BLOCK" for r in rows)
        waiting = sum(r.execution == "WOULD_WAIT" for r in rows)
        winners = sum(r.execution == "WOULD_TAKE" and r.outcome_result == "WIN" for r in rows)
        losers = sum(r.execution == "WOULD_TAKE" and r.outcome_result == "LOSS" for r in rows)
        net = sum((r.outcome_points or 0.0) for r in rows if r.execution == "WOULD_TAKE")
        recommendations, decision_accuracy = self._aggregate_learning(rows)
        correct_takes = sum(r.verdict == "CORRECT_TAKE" for r in rows)
        false_positives = sum(r.verdict == "FALSE_POSITIVE" for r in rows)
        missed_opportunities = sum(r.verdict == "MISSED_OPPORTUNITY" for r in rows)
        correct_skips = sum(r.verdict == "CORRECT_SKIP" for r in rows)
        incorrect_blocks = sum(r.verdict == "INCORRECT_BLOCK" for r in rows)
        correct_blocks = sum(r.verdict == "CORRECT_BLOCK" for r in rows)
        return HistoricalDecisionReplayResult(
            trading_date=trading_date,
            rows=tuple(rows),
            active_signals=len(active),
            approved=approved,
            blocked=blocked,
            waiting=waiting,
            expired=0,
            winners=winners,
            losers=losers,
            net_points=round(net, 2),
            data_fidelity="POINT_IN_TIME_UNDERLYING; NO_INTRADAY_OPTION_LOOKAHEAD",
            correct_takes=correct_takes,
            false_positives=false_positives,
            missed_opportunities=missed_opportunities,
            correct_skips=correct_skips,
            incorrect_blocks=incorrect_blocks,
            correct_blocks=correct_blocks,
            decision_accuracy_pct=decision_accuracy,
            learning_recommendations=recommendations,
        )

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib

import pandas as pd

from red_bar_lab.options.context import summarize_option_chain

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


@dataclass(frozen=True)
class CollectorTickReport:
    mode: str
    status: str
    snapshot_id: int | None
    snapshot_timestamp: str | None
    expiry: str | None
    signals_linked: int
    chain_path: Path | None
    message: str


def market_clock_mode(now: datetime | None = None) -> str:
    return (
        "ONLINE"
        if market_session_phase(now) == "OPEN"
        else "OFFLINE"
    )


def market_session_phase(now: datetime | None = None) -> str:
    now = now or datetime.now(IST)
    local = now.astimezone(IST)
    if local.weekday() >= 5:
        return "WEEKEND"
    if local.time() < MARKET_OPEN:
        return "PREOPEN"
    if local.time() <= MARKET_CLOSE:
        return "OPEN"
    return "POSTCLOSE"


class RedBarDualMarketCollector:
    def __init__(self, provider, database, settings):
        self.provider = provider
        self.database = database
        self.settings = settings

    @staticmethod
    def _snapshot_key(
        instrument_key: str,
        expiry: str,
        snapshot_timestamp: datetime,
        mode: str,
    ) -> str:
        # One continuous history row per instrument/expiry/minute/mode.
        bucket = snapshot_timestamp.astimezone(IST).replace(
            second=0,
            microsecond=0,
        ).isoformat()
        raw = f"{instrument_key}|{expiry}|{bucket}|{mode}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _fetch_chain(
        self,
        instrument_key: str,
        expiry: str | None,
    ):
        expiries = self.provider.option_expiries(instrument_key)
        chosen = expiry or expiries[0]
        records = self.provider.option_chain(instrument_key, chosen)
        chain = self.provider.option_chain_dataframe(records)
        if chain is None or chain.empty:
            raise ValueError("Upstox returned an empty option chain.")
        return chosen, chain

    def _persist_raw_snapshot(
        self,
        *,
        instrument_key: str,
        trading_date: str,
        expiry: str,
        chain: pd.DataFrame,
        snapshot_timestamp: datetime,
        mode: str,
    ):
        safe_instrument = instrument_key.replace("|", "_")
        stamp = snapshot_timestamp.astimezone(IST).strftime(
            "%Y%m%d_%H%M%S"
        )
        chain_path = (
            self.settings.artifacts_root
            / "options"
            / "history"
            / safe_instrument
            / trading_date
            / f"{mode.lower()}_{stamp}_{expiry}_chain.csv"
        )
        chain_path.parent.mkdir(parents=True, exist_ok=True)
        chain.to_csv(chain_path, index=False)

        # Reuse the proven option-chain summarizer with a synthetic timestamp
        # solely to derive chain-level fields. Signal linking is handled later.
        synthetic = {
            "signal_id": "__MARKET_SNAPSHOT__",
            "trading_date": trading_date,
            "confirmation_timestamp": snapshot_timestamp.isoformat(),
        }
        summary = summarize_option_chain(
            signal=synthetic,
            instrument_key=instrument_key,
            expiry=expiry,
            chain=chain,
            snapshot_timestamp=snapshot_timestamp,
            alignment_tolerance_seconds=0,
            chain_artifact_path=str(chain_path),
        )

        history_row = {
            "snapshot_key": self._snapshot_key(
                instrument_key,
                expiry,
                snapshot_timestamp,
                mode,
            ),
            "instrument_key": instrument_key,
            "trading_date": trading_date,
            "option_expiry": expiry,
            "snapshot_timestamp": snapshot_timestamp.isoformat(),
            "collector_mode": mode,
            "option_spot_price": summary.get("option_spot_price"),
            "atm_strike": summary.get("atm_strike"),
            "total_call_oi": summary.get("total_call_oi"),
            "total_put_oi": summary.get("total_put_oi"),
            "pcr_oi": summary.get("pcr_oi"),
            "total_call_oi_change": summary.get(
                "total_call_oi_change"
            ),
            "total_put_oi_change": summary.get(
                "total_put_oi_change"
            ),
            "pcr_oi_change": summary.get("pcr_oi_change"),
            "call_wall_strike": summary.get("call_wall_strike"),
            "put_wall_strike": summary.get("put_wall_strike"),
            "max_pain_strike": summary.get("max_pain_strike"),
            "atm_call_iv": summary.get("atm_call_iv"),
            "atm_put_iv": summary.get("atm_put_iv"),
            "atm_call_delta": summary.get("atm_call_delta"),
            "atm_put_delta": summary.get("atm_put_delta"),
            "atm_call_gamma": summary.get("atm_call_gamma"),
            "atm_put_gamma": summary.get("atm_put_gamma"),
            "atm_call_theta": summary.get("atm_call_theta"),
            "atm_put_theta": summary.get("atm_put_theta"),
            "atm_call_vega": summary.get("atm_call_vega"),
            "atm_put_vega": summary.get("atm_put_vega"),
            "chain_artifact_path": str(chain_path),
        }
        snapshot_id = self.database.upsert_option_chain_history(
            history_row
        )
        return snapshot_id, chain_path, history_row

    @staticmethod
    def _signal_context_from_history(
        signal: dict[str, object],
        snapshot: dict[str, object],
    ) -> dict[str, object]:
        entry_ts = pd.Timestamp(signal["confirmation_timestamp"])
        snap_ts = pd.Timestamp(snapshot["snapshot_timestamp"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("Asia/Kolkata")
        else:
            entry_ts = entry_ts.tz_convert("Asia/Kolkata")
        if snap_ts.tzinfo is None:
            snap_ts = snap_ts.tz_localize("Asia/Kolkata")
        else:
            snap_ts = snap_ts.tz_convert("Asia/Kolkata")

        delay = (snap_ts - entry_ts).total_seconds()

        return {
            "signal_id": signal.get("signal_id"),
            "instrument_key": signal.get("instrument_key")
            or snapshot.get("instrument_key"),
            "trading_date": str(signal.get("trading_date")),
            "entry_timestamp": entry_ts.isoformat(),
            "option_expiry": snapshot.get("option_expiry"),
            "option_snapshot_timestamp": snap_ts.isoformat(),
            "option_snapshot_delay_seconds": float(delay),
            "entry_aligned": 1,
            "option_spot_price": snapshot.get("option_spot_price"),
            "atm_strike": snapshot.get("atm_strike"),
            "total_call_oi": snapshot.get("total_call_oi"),
            "total_put_oi": snapshot.get("total_put_oi"),
            "pcr_oi": snapshot.get("pcr_oi"),
            "total_call_oi_change": snapshot.get(
                "total_call_oi_change"
            ),
            "total_put_oi_change": snapshot.get(
                "total_put_oi_change"
            ),
            "pcr_oi_change": snapshot.get("pcr_oi_change"),
            "call_wall_strike": snapshot.get("call_wall_strike"),
            "put_wall_strike": snapshot.get("put_wall_strike"),
            "max_pain_strike": snapshot.get("max_pain_strike"),
            "atm_call_iv": snapshot.get("atm_call_iv"),
            "atm_put_iv": snapshot.get("atm_put_iv"),
            "atm_call_delta": snapshot.get("atm_call_delta"),
            "atm_put_delta": snapshot.get("atm_put_delta"),
            "atm_call_gamma": snapshot.get("atm_call_gamma"),
            "atm_put_gamma": snapshot.get("atm_put_gamma"),
            "atm_call_theta": snapshot.get("atm_call_theta"),
            "atm_put_theta": snapshot.get("atm_put_theta"),
            "atm_call_vega": snapshot.get("atm_call_vega"),
            "atm_put_vega": snapshot.get("atm_put_vega"),
            "chain_artifact_path": snapshot.get(
                "chain_artifact_path"
            ),
        }

    def link_nearest_pre_entry_snapshots(
        self,
        *,
        instrument_key: str,
        trading_date: str,
        max_age_seconds: int = 120,
    ) -> int:
        signals = self.database.read_signal_attempts(
            instrument_key,
            trading_date,
        )
        linked = 0

        for signal in signals:
            if (
                not signal.get("signal_id")
                or not signal.get("confirmation_timestamp")
                or signal.get("state") != "ACTIVE"
            ):
                continue

            existing = self.database.read_option_context_by_signal(
                str(signal["signal_id"])
            )
            if existing and bool(existing.get("entry_aligned")):
                continue

            snapshot = self.database.find_nearest_pre_entry_option_snapshot(
                instrument_key=instrument_key,
                entry_timestamp=str(
                    signal["confirmation_timestamp"]
                ),
                max_age_seconds=max_age_seconds,
            )
            if not snapshot:
                continue

            row = self._signal_context_from_history(signal, snapshot)
            self.database.upsert_option_context_snapshots([row])
            self.database.upsert_signal_option_snapshot_link(
                signal_id=str(signal["signal_id"]),
                snapshot_id=int(snapshot["id"]),
                relation="PRE_ENTRY",
                delta_seconds=float(
                    row["option_snapshot_delay_seconds"]
                ),
                authoritative=1,
            )
            linked += 1

        return linked

    def online_tick(
        self,
        *,
        instrument_key: str,
        expiry: str | None = None,
        link_window_seconds: int = 120,
        now: datetime | None = None,
    ) -> CollectorTickReport:
        now = (now or datetime.now(IST)).astimezone(IST)
        trading_date = now.date().isoformat()

        if market_clock_mode(now) != "ONLINE":
            report = CollectorTickReport(
                mode="ONLINE",
                status="SKIPPED",
                snapshot_id=None,
                snapshot_timestamp=None,
                expiry=expiry,
                signals_linked=0,
                chain_path=None,
                message="Outside regular market hours.",
            )
            self.database.update_collector_status(
                "DUAL_OPTIONS",
                "ONLINE",
                report.status,
                report.message,
                None,
            )
            return report

        chosen, chain = self._fetch_chain(
            instrument_key,
            expiry,
        )
        snapshot_id, chain_path, _ = self._persist_raw_snapshot(
            instrument_key=instrument_key,
            trading_date=trading_date,
            expiry=chosen,
            chain=chain,
            snapshot_timestamp=now,
            mode="ONLINE",
        )

        linked = self.link_nearest_pre_entry_snapshots(
            instrument_key=instrument_key,
            trading_date=trading_date,
            max_age_seconds=link_window_seconds,
        )

        report = CollectorTickReport(
            mode="ONLINE",
            status="OK",
            snapshot_id=snapshot_id,
            snapshot_timestamp=now.isoformat(),
            expiry=chosen,
            signals_linked=linked,
            chain_path=chain_path,
            message=(
                f"Stored online option snapshot; linked "
                f"{linked} signal(s)."
            ),
        )
        self.database.update_collector_status(
            "DUAL_OPTIONS",
            "ONLINE",
            report.status,
            report.message,
            snapshot_id,
        )
        return report

    def offline_eod_tick(
        self,
        *,
        instrument_key: str,
        trading_date: str | None = None,
        expiry: str | None = None,
        now: datetime | None = None,
    ) -> CollectorTickReport:
        now = (now or datetime.now(IST)).astimezone(IST)
        target_date = trading_date or now.date().isoformat()

        chosen, chain = self._fetch_chain(
            instrument_key,
            expiry,
        )
        snapshot_id, chain_path, _ = self._persist_raw_snapshot(
            instrument_key=instrument_key,
            trading_date=target_date,
            expiry=chosen,
            chain=chain,
            snapshot_timestamp=now,
            mode="EOD",
        )

        report = CollectorTickReport(
            mode="OFFLINE",
            status="OK",
            snapshot_id=snapshot_id,
            snapshot_timestamp=now.isoformat(),
            expiry=chosen,
            signals_linked=0,
            chain_path=chain_path,
            message="Stored offline/EOD option snapshot.",
        )
        self.database.update_collector_status(
            "DUAL_OPTIONS",
            "OFFLINE",
            report.status,
            report.message,
            snapshot_id,
        )
        return report

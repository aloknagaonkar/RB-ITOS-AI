from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.services.upstox_service import RedBarUpstoxService

IST = "Asia/Kolkata"


def _safe(value: object) -> str:
    return str(value or "").replace("|", "_").replace("/", "_").replace("\\", "_").replace(" ", "_")


def _f(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class OptionContractCoverage:
    instrument_key: str
    symbol: str
    option_type: str
    strike: float
    expected_bars: int
    stored_bars: int
    candle_coverage_pct: float
    missing_bars: int
    oi_bars: int
    status: str


@dataclass(frozen=True)
class OptionChainCoverageReport:
    trading_date: date
    expiry: str | None
    contracts_discovered: int
    contracts_stored: int
    ce_discovered: int
    pe_discovered: int
    ce_stored: int
    pe_stored: int
    expected_bars: int
    stored_bars: int
    candle_coverage_pct: float
    oi_coverage_pct: float
    contract_coverage_pct: float
    missing_contracts: int
    fidelity: str
    replay_ready: bool
    reason: str
    contracts: tuple[OptionContractCoverage, ...]
    data_source: str = "EXPIRED_OPTION_CANDLES"
    snapshot_coverage_pct: float = 0.0
    live_snapshots: int = 0
    bid_ask_available: bool = False
    iv_available: bool = False
    greeks_available: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            **{k: v for k, v in self.__dict__.items() if k != "contracts"},
            "trading_date": self.trading_date.isoformat(),
            "contracts": [item.__dict__.copy() for item in self.contracts],
        }


@dataclass(frozen=True)
class HistoricalOptionSyncResult:
    trading_date: date
    expiry: str | None
    discovered: int
    downloaded: int
    reused: int
    failed: int
    rows_stored: int
    errors: tuple[str, ...]
    coverage: OptionChainCoverageReport


class HistoricalOptionChainStore:
    """Local cache for expired-option contract metadata and one-minute candles."""

    def __init__(self, layout: ArtifactLayout, provider_name: str = "upstox") -> None:
        self.layout = layout
        self.provider_name = provider_name

    def _root(self, instrument_key: str, trading_date: date) -> Path:
        return (
            self.layout.settings.historical_root
            / self.provider_name
            / "options"
            / _safe(instrument_key)
            / trading_date.isoformat()
        )

    def manifest_path(self, instrument_key: str, trading_date: date) -> Path:
        return self._root(instrument_key, trading_date) / "contracts.json"

    def candle_path(self, instrument_key: str, trading_date: date, expired_key: str) -> Path:
        return self._root(instrument_key, trading_date) / "candles" / f"{_safe(expired_key)}.csv"

    def write_manifest(self, instrument_key: str, trading_date: date, expiry: str, contracts: list[dict[str, object]]) -> None:
        path = self.manifest_path(instrument_key, trading_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"expiry": expiry, "contracts": contracts}, indent=2, default=str), encoding="utf-8")

    def read_manifest(self, instrument_key: str, trading_date: date) -> dict[str, object]:
        path = self.manifest_path(instrument_key, trading_date)
        if not path.exists():
            return {"expiry": None, "contracts": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"expiry": None, "contracts": []}
        except Exception:
            return {"expiry": None, "contracts": []}

    def write_candles(self, instrument_key: str, trading_date: date, expired_key: str, frame: pd.DataFrame) -> int:
        path = self.candle_path(instrument_key, trading_date, expired_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        work = frame.copy()
        if "timestamp" in work.columns:
            work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce", utc=True)
            work = work.dropna(subset=["timestamp"]).drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
        work.to_csv(path, index=False)
        return len(work)

    def read_candles(self, instrument_key: str, trading_date: date, expired_key: str) -> pd.DataFrame:
        path = self.candle_path(instrument_key, trading_date, expired_key)
        if not path.exists():
            return pd.DataFrame()
        frame = pd.read_csv(path)
        if "timestamp" in frame.columns:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
            frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        return frame.reset_index(drop=True)


class HistoricalOptionChainSyncService:
    """Download and prove historical expired-option candle completeness.

    Upstox historical expired-option endpoints provide OHLC/volume/OI candles,
    not historical order-book bid/ask, IV or Greeks. Those fields are therefore
    never fabricated and fidelity can never be labelled full live microstructure
    parity from this source alone.
    """

    def __init__(self, provider: RedBarUpstoxService, layout: ArtifactLayout, historical, database=None) -> None:
        self.provider = provider
        self.store = HistoricalOptionChainStore(layout)
        self.historical = historical
        self.database = database
        self._live_snapshot_cache: dict[tuple[str, date], list[tuple[pd.Timestamp, dict[str, object], pd.DataFrame]]] = {}
        self._expiry_probe_cache: dict[tuple[str, date], tuple[dict[str, object], ...]] = {}

    @staticmethod
    def _contract_key(row: dict[str, object]) -> str:
        for key in ("instrument_key", "instrument_token", "expired_instrument_key"):
            value = row.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _symbol(row: dict[str, object]) -> str:
        return str(row.get("trading_symbol") or row.get("tradingsymbol") or row.get("symbol") or "")

    @staticmethod
    def _option_type(row: dict[str, object]) -> str:
        raw = str(row.get("instrument_type") or row.get("option_type") or row.get("type") or "").upper()
        if raw.endswith("CE") or raw == "CE" or "CALL" in raw:
            return "CE"
        if raw.endswith("PE") or raw == "PE" or "PUT" in raw:
            return "PE"
        symbol = HistoricalOptionChainSyncService._symbol(row).upper()
        return "CE" if "CE" in symbol[-4:] else "PE" if "PE" in symbol[-4:] else raw

    @staticmethod
    def _strike(row: dict[str, object]) -> float:
        return _f(row.get("strike_price", row.get("strike")))

    @staticmethod
    def _parse_expiry_value(value: object) -> date | None:
        """Normalize provider expiry values without assuming one wire format.

        Upstox normally returns ISO dates, but keeping the parser tolerant makes
        replay diagnostics resilient to SDK/wrapper representations such as
        datetimes, pandas timestamps, dictionaries, or display-formatted dates.
        """
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, dict):
            for key in ("expiry", "expiry_date", "date"):
                if value.get(key):
                    return HistoricalOptionChainSyncService._parse_expiry_value(value.get(key))
            return None
        text = str(value).strip()
        if not text:
            return None
        # Fast path for the documented API format.
        try:
            return date.fromisoformat(text[:10])
        except (TypeError, ValueError):
            pass
        # Tolerate common display formats without hard-coding an expiry weekday.
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
            try:
                return pd.to_datetime(text, format=fmt, errors="raise").date()
            except (TypeError, ValueError):
                continue
        try:
            parsed = pd.to_datetime(text, errors="raise")
            return parsed.date()
        except (TypeError, ValueError, OverflowError):
            return None

    def _probe_expiry_contracts(self, instrument_key: str, expiry_date: date) -> tuple[dict[str, object], ...]:
        """Verify an inferred expiry by asking the provider for actual expired contracts.

        The expiry-list endpoint can lag the contract endpoint by a session.  A replay
        must never back-select an already-expired series merely to make data exist, so
        an inferred expiry is accepted only when the provider itself returns contracts.
        """
        cache_key = (instrument_key, expiry_date)
        cached = self._expiry_probe_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            rows = tuple(dict(row) for row in (self.provider.expired_option_contracts(
                instrument_key, expiry_date.isoformat()
            ) or []) if isinstance(row, dict))
        except Exception:
            rows = ()
        self._expiry_probe_cache[cache_key] = rows
        return rows

    def _probe_missing_expiry(self, instrument_key: str, trading_date: date, parsed_dates: list[date]) -> tuple[date | None, tuple[str, ...]]:
        """Find a provider-verified expiry when the expiry-list endpoint is stale.

        Probe a small, bounded window only.  Start with the cadence implied by the two
        latest provider expiries (normally seven days), then try remaining dates from
        the replay day forward.  No date before the replay day can ever be selected.
        """
        today = date.today()
        if trading_date > today or not parsed_dates:
            return None, ()
        upper = min(today, trading_date + timedelta(days=14))
        candidates: list[date] = []
        if len(parsed_dates) >= 2:
            cadence_days = (parsed_dates[-1] - parsed_dates[-2]).days
            if 1 <= cadence_days <= 14:
                inferred = parsed_dates[-1] + timedelta(days=cadence_days)
                if trading_date <= inferred <= upper:
                    candidates.append(inferred)
        for offset in range((upper - trading_date).days + 1):
            item = trading_date + timedelta(days=offset)
            if item not in candidates:
                candidates.append(item)
        probed: list[str] = []
        for candidate in candidates:
            probed.append(candidate.isoformat())
            if self._probe_expiry_contracts(instrument_key, candidate):
                return candidate, tuple(probed)
        return None, tuple(probed)

    def expiry_resolution_details(self, instrument_key: str, trading_date: date) -> dict[str, object]:
        raw = list(self.provider.expired_option_expiries(instrument_key) or [])
        parsed_pairs: list[tuple[date, object]] = []
        unparsed: list[str] = []
        for value in raw:
            parsed = self._parse_expiry_value(value)
            if parsed is None:
                unparsed.append(str(value))
            else:
                parsed_pairs.append((parsed, value))
        parsed_dates = sorted({item for item, _ in parsed_pairs})
        eligible = [item for item in parsed_dates if item >= trading_date]
        selected = eligible[0] if eligible else None
        resolution_source = "EXPIRY_LIST"
        probed_dates: tuple[str, ...] = ()
        if selected is None:
            selected, probed_dates = self._probe_missing_expiry(instrument_key, trading_date, parsed_dates)
            if selected is not None:
                resolution_source = "CONTRACT_ENDPOINT_PROBE"
        previous = [item for item in parsed_dates if item < trading_date]
        visible_candidates = list(eligible[:8])
        if selected is not None and selected not in visible_candidates:
            visible_candidates.insert(0, selected)
        return {
            "raw_count": len(raw),
            "parsed_count": len(parsed_pairs),
            "unparsed_count": len(unparsed),
            "unparsed_sample": tuple(unparsed[:5]),
            "earliest": parsed_dates[0].isoformat() if parsed_dates else None,
            "latest": parsed_dates[-1].isoformat() if parsed_dates else None,
            "previous": previous[-1].isoformat() if previous else None,
            "next": selected.isoformat() if selected else None,
            "candidate_expiries": tuple(item.isoformat() for item in visible_candidates),
            "selected": selected.isoformat() if selected else None,
            "rule": "FIRST_PROVIDER_EXPIRY_ON_OR_AFTER_TRADING_DATE_THEN_PROVIDER_VERIFIED_PROBE",
            "resolution_source": resolution_source if selected is not None else "NONE",
            "probed_dates": probed_dates,
        }

    def _select_expiry(self, instrument_key: str, trading_date: date) -> str | None:
        return self.expiry_resolution_details(instrument_key, trading_date)["selected"]

    def sync_day(self, instrument_key: str, trading_date: date, *, force: bool = False, max_workers: int = 6) -> HistoricalOptionSyncResult:
        expiry = self._select_expiry(instrument_key, trading_date)
        if not expiry:
            coverage = self.validate_day(instrument_key, trading_date)
            return HistoricalOptionSyncResult(trading_date, None, 0, 0, 0, 0, 0, ("No historical expiry available",), coverage)
        probe_cached = self._expiry_probe_cache.get((instrument_key, date.fromisoformat(expiry)))
        contracts = list(probe_cached) if probe_cached is not None else self.provider.expired_option_contracts(instrument_key, expiry)
        normalized = [dict(row) for row in contracts if self._contract_key(row)]
        self.store.write_manifest(instrument_key, trading_date, expiry, normalized)

        downloaded = reused = failed = rows_stored = 0
        errors: list[str] = []
        todo: list[tuple[str, dict[str, object]]] = []
        for row in normalized:
            key = self._contract_key(row)
            path = self.store.candle_path(instrument_key, trading_date, key)
            if path.exists() and not force:
                reused += 1
            else:
                todo.append((key, row))

        def fetch(key: str):
            frame = self.provider.expired_option_historical_candles(
                key, trading_date.isoformat(), interval_minutes=1
            )
            if not frame.empty and "timestamp" in frame.columns:
                ts = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
                local = ts.dt.tz_convert(IST).dt.date
                frame = frame.loc[local == trading_date].reset_index(drop=True)
            return key, frame

        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(todo) or 1))) as pool:
            futures = {pool.submit(fetch, key): (key, row) for key, row in todo}
            for future in as_completed(futures):
                key, row = futures[future]
                try:
                    _, frame = future.result()
                    count = self.store.write_candles(instrument_key, trading_date, key, frame)
                    rows_stored += count
                    downloaded += 1
                except Exception as exc:
                    failed += 1
                    errors.append(f"{self._symbol(row) or key}: {type(exc).__name__}: {exc}")
        coverage = self.validate_day(instrument_key, trading_date)
        return HistoricalOptionSyncResult(trading_date, expiry, len(normalized), downloaded, reused, failed, rows_stored, tuple(errors), coverage)

    def _validate_expired_day(self, instrument_key: str, trading_date: date) -> OptionChainCoverageReport:
        manifest = self.store.read_manifest(instrument_key, trading_date)
        contracts = [dict(row) for row in (manifest.get("contracts") or []) if isinstance(row, dict)]
        expiry = manifest.get("expiry")
        underlying = self.historical.read_day(instrument_key, trading_date, interval_minutes=1)
        expected_ts: set[pd.Timestamp] = set()
        if not underlying.empty and "timestamp" in underlying.columns:
            raw = pd.to_datetime(underlying["timestamp"], errors="coerce", utc=True).dropna()
            expected_ts = {pd.Timestamp(v).floor("min") for v in raw}
        expected_per_contract = len(expected_ts)

        details: list[OptionContractCoverage] = []
        total_stored = total_expected = oi_bars = 0
        ce_discovered = sum(self._option_type(row) == "CE" for row in contracts)
        pe_discovered = sum(self._option_type(row) == "PE" for row in contracts)
        ce_stored = pe_stored = stored_contracts = 0
        for row in contracts:
            key = self._contract_key(row)
            frame = self.store.read_candles(instrument_key, trading_date, key)
            stored_ts: set[pd.Timestamp] = set()
            if not frame.empty and "timestamp" in frame.columns:
                raw = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True).dropna()
                stored_ts = {pd.Timestamp(v).floor("min") for v in raw}
            if expected_ts:
                matched = len(expected_ts & stored_ts)
                missing = len(expected_ts - stored_ts)
                expected = len(expected_ts)
            else:
                matched = len(stored_ts)
                missing = 0
                expected = len(stored_ts)
            pct = round((matched / expected * 100.0), 2) if expected else 0.0
            oi_count = 0
            if not frame.empty and "oi" in frame.columns:
                oi = pd.to_numeric(frame["oi"], errors="coerce")
                oi_count = int(oi.notna().sum())
            status = "COMPLETE" if pct >= 98.0 else "PARTIAL" if pct >= 80.0 else "MISSING"
            typ = self._option_type(row)
            if not frame.empty:
                stored_contracts += 1
                if typ == "CE": ce_stored += 1
                elif typ == "PE": pe_stored += 1
            total_stored += matched
            total_expected += expected
            oi_bars += oi_count
            details.append(OptionContractCoverage(key, self._symbol(row), typ, self._strike(row), expected, matched, pct, missing, oi_count, status))

        contract_count = len(contracts)
        contract_cov = round(stored_contracts / contract_count * 100.0, 2) if contract_count else 0.0
        candle_cov = round(total_stored / total_expected * 100.0, 2) if total_expected else 0.0
        oi_cov = round(oi_bars / total_expected * 100.0, 2) if total_expected else 0.0
        missing_contracts = max(0, contract_count - stored_contracts)
        # Full live parity is impossible without historical bid/ask/IV/Greeks.
        if contract_cov >= 95.0 and candle_cov >= 98.0:
            fidelity, ready = "PARTIAL_LIVE_PARITY_HIGH", True
            reason = "Option price/volume/OI coverage is high; historical bid/ask, IV and Greeks remain unavailable."
        elif contract_cov >= 80.0 and candle_cov >= 90.0:
            fidelity, ready = "PARTIAL_OPTION_REPLAY", True
            reason = "Usable but incomplete option coverage; decisions must be treated as partial-parity research."
        else:
            fidelity, ready = "UNRELIABLE_OPTION_REPLAY", False
            reason = "Historical option contract/candle coverage is below replay-readiness thresholds."
        return OptionChainCoverageReport(trading_date, str(expiry) if expiry else None, contract_count, stored_contracts,
            ce_discovered, pe_discovered, ce_stored, pe_stored, total_expected, total_stored, candle_cov, oi_cov,
            contract_cov, missing_contracts, fidelity, ready, reason, tuple(details))

    @staticmethod
    def _artifact_chain(path_value: object) -> pd.DataFrame:
        if not path_value:
            return pd.DataFrame()
        try:
            path = Path(str(path_value))
            if not path.exists():
                return pd.DataFrame()
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()

    def _live_snapshots(self, instrument_key: str, trading_date: date) -> list[tuple[pd.Timestamp, dict[str, object], pd.DataFrame]]:
        cache_key = (instrument_key, trading_date)
        cached = self._live_snapshot_cache.get(cache_key)
        if cached is not None:
            return cached
        if self.database is None:
            self._live_snapshot_cache[cache_key] = []
            return []
        rows = self.database.read_option_chain_history(
            instrument_key, trading_date.isoformat(), trading_date.isoformat(), limit=2000
        )
        snapshots: list[tuple[pd.Timestamp, dict[str, object], pd.DataFrame]] = []
        for row in rows:
            if str(row.get("collector_mode") or "").upper() != "ONLINE":
                continue
            ts = pd.Timestamp(row.get("snapshot_timestamp"))
            if pd.isna(ts):
                continue
            if ts.tzinfo is None:
                ts = ts.tz_localize(IST)
            else:
                ts = ts.tz_convert(IST)
            chain = self._artifact_chain(row.get("chain_artifact_path"))
            if chain.empty:
                continue
            snapshots.append((ts, dict(row), chain))
        snapshots.sort(key=lambda item: item[0])
        self._live_snapshot_cache[cache_key] = snapshots
        return snapshots

    @staticmethod
    def _has_numeric(chain: pd.DataFrame, columns: tuple[str, ...]) -> bool:
        for col in columns:
            if col in chain.columns and pd.to_numeric(chain[col], errors="coerce").notna().any():
                return True
        return False

    def _validate_live_day(self, instrument_key: str, trading_date: date) -> OptionChainCoverageReport | None:
        snapshots = self._live_snapshots(instrument_key, trading_date)
        if not snapshots:
            return None
        underlying = self.historical.read_day(instrument_key, trading_date, interval_minutes=1)
        expected_ts: set[pd.Timestamp] = set()
        if not underlying.empty and "timestamp" in underlying.columns:
            raw = pd.to_datetime(underlying["timestamp"], errors="coerce", utc=True).dropna()
            expected_ts = {pd.Timestamp(v).tz_convert(IST).floor("min") for v in raw}
        snapshot_ts = {ts.floor("min") for ts, _, _ in snapshots}
        matched = len(expected_ts & snapshot_ts) if expected_ts else len(snapshot_ts)
        expected = len(expected_ts) if expected_ts else len(snapshot_ts)
        snapshot_cov = round(matched / expected * 100.0, 2) if expected else 0.0

        latest_chain = snapshots[-1][2]
        strikes = pd.to_numeric(latest_chain.get("strike"), errors="coerce") if "strike" in latest_chain.columns else pd.Series(dtype=float)
        valid_strikes = int(strikes.notna().sum())
        contracts = valid_strikes * 2
        bid_ask = self._has_numeric(latest_chain, ("call_bid", "call_ask", "put_bid", "put_ask"))
        iv = self._has_numeric(latest_chain, ("call_iv", "put_iv"))
        greeks = self._has_numeric(latest_chain, ("call_delta", "put_delta", "call_gamma", "put_gamma"))
        oi = self._has_numeric(latest_chain, ("call_oi", "put_oi"))
        oi_cov = 100.0 if oi else 0.0

        if snapshot_cov >= 80.0 and contracts > 0:
            fidelity, ready = "LIVE_CAPTURE_PARITY_HIGH", True
            reason = "Using same-day ONLINE option-chain snapshots captured by ITOS; point-in-time bid/ask, IV and Greeks are used when present."
        elif snapshot_cov >= 50.0 and contracts > 0:
            fidelity, ready = "LIVE_CAPTURE_PARTIAL", True
            reason = "Using same-day ONLINE option-chain snapshots, but temporal coverage is incomplete; replay remains partial parity."
        else:
            fidelity, ready = "UNRELIABLE_LIVE_CAPTURE", False
            reason = "Same-day live option snapshots exist, but temporal coverage is below the replay-readiness threshold."

        return OptionChainCoverageReport(
            trading_date, str(snapshots[-1][1].get("option_expiry") or "") or None,
            contracts, contracts, valid_strikes, valid_strikes, valid_strikes, valid_strikes,
            expected, matched, snapshot_cov, oi_cov, 100.0 if contracts else 0.0, 0,
            fidelity, ready, reason, (),
            data_source="LIVE_MARKET_CAPTURE", snapshot_coverage_pct=snapshot_cov,
            live_snapshots=len(snapshots), bid_ask_available=bid_ask,
            iv_available=iv, greeks_available=greeks,
        )

    def validate_day(self, instrument_key: str, trading_date: date) -> OptionChainCoverageReport:
        live = self._validate_live_day(instrument_key, trading_date)
        if live is not None and live.replay_ready:
            return live
        expired = self._validate_expired_day(instrument_key, trading_date)
        if expired.replay_ready:
            return expired
        return live if live is not None else expired

    @staticmethod
    def _live_contract_row(chain_row: pd.Series, side: str, expiry: str | None) -> dict[str, object]:
        prefix = "call" if side == "CE" else "put"
        strike = _f(chain_row.get("strike"))
        instrument_key = str(chain_row.get(f"{prefix}_instrument_key") or f"LIVE|{strike:.0f}|{side}")
        return {
            "instrument_key": instrument_key,
            "trading_symbol": f"NIFTY {strike:.0f} {side}",
            "instrument_type": side,
            "strike_price": strike,
            "expiry": expiry,
            "lot_size": 75,
        }

    @staticmethod
    def _live_frame_row(ts: pd.Timestamp, chain_row: pd.Series, side: str) -> dict[str, object]:
        prefix = "call" if side == "CE" else "put"
        ltp = _f(chain_row.get(f"{prefix}_ltp"))
        return {
            "timestamp": ts.tz_convert("UTC"),
            "open": ltp, "high": ltp, "low": ltp, "close": ltp,
            "volume": _f(chain_row.get(f"{prefix}_volume")),
            "oi": _f(chain_row.get(f"{prefix}_oi")),
            "best_bid": _f(chain_row.get(f"{prefix}_bid")),
            "best_bid_qty": _f(chain_row.get(f"{prefix}_bid_qty")),
            "best_ask": _f(chain_row.get(f"{prefix}_ask")),
            "best_ask_qty": _f(chain_row.get(f"{prefix}_ask_qty")),
            "iv": _f(chain_row.get(f"{prefix}_iv")),
            "delta": _f(chain_row.get(f"{prefix}_delta")),
            "gamma": _f(chain_row.get(f"{prefix}_gamma")),
            "theta": _f(chain_row.get(f"{prefix}_theta")),
            "vega": _f(chain_row.get(f"{prefix}_vega")),
        }

    def _live_contract_series(self, snapshots, *, instrument_key: str, strike: float, side: str) -> pd.DataFrame:
        prefix = "call" if side == "CE" else "put"
        rows = []
        for ts, _, chain in snapshots:
            if "strike" not in chain.columns:
                continue
            strikes = pd.to_numeric(chain["strike"], errors="coerce")
            match = chain.loc[(strikes - float(strike)).abs() < 1e-6]
            if match.empty:
                continue
            row = match.iloc[0]
            side_key = str(row.get(f"{prefix}_instrument_key") or "")
            if instrument_key and side_key and side_key != instrument_key:
                continue
            rows.append(self._live_frame_row(ts, row, side))
        return pd.DataFrame(rows)

    def _live_point_in_time_contracts(self, instrument_key: str, trading_date: date, moment) -> list[tuple[dict[str, object], pd.DataFrame]]:
        snapshots = self._live_snapshots(instrument_key, trading_date)
        if not snapshots:
            return []
        ts = pd.Timestamp(moment)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        prior = [item for item in snapshots if item[0] <= ts]
        if not prior:
            return []
        latest_ts, latest_meta, latest_chain = prior[-1]
        # Do not use a stale live snapshot as though it were exact market state.
        if (ts - latest_ts).total_seconds() > 180:
            return []
        result = []
        for _, chain_row in latest_chain.iterrows():
            for side in ("CE", "PE"):
                raw = self._live_contract_row(chain_row, side, str(latest_meta.get("option_expiry") or "") or None)
                frame = self._live_contract_series(prior, instrument_key=str(raw["instrument_key"]), strike=float(raw["strike_price"]), side=side)
                if not frame.empty:
                    result.append((raw, frame.reset_index(drop=True)))
        return result

    def full_contract_candles(self, instrument_key: str, trading_date: date, contract_row: dict[str, object]) -> pd.DataFrame:
        coverage = self.validate_day(instrument_key, trading_date)
        if coverage.data_source == "LIVE_MARKET_CAPTURE":
            snapshots = self._live_snapshots(instrument_key, trading_date)
            side = self._option_type(contract_row)
            return self._live_contract_series(
                snapshots,
                instrument_key=self._contract_key(contract_row),
                strike=self._strike(contract_row),
                side=side,
            ).reset_index(drop=True)
        key = self._contract_key(contract_row)
        return self.store.read_candles(instrument_key, trading_date, key)

    def point_in_time_contracts(self, instrument_key: str, trading_date: date, moment) -> list[tuple[dict[str, object], pd.DataFrame]]:
        coverage = self.validate_day(instrument_key, trading_date)
        if coverage.data_source == "LIVE_MARKET_CAPTURE":
            return self._live_point_in_time_contracts(instrument_key, trading_date, moment)
        manifest = self.store.read_manifest(instrument_key, trading_date)
        result = []
        ts = pd.Timestamp(moment)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        ts_utc = ts.tz_convert("UTC")
        for raw in manifest.get("contracts") or []:
            if not isinstance(raw, dict):
                continue
            key = self._contract_key(raw)
            frame = self.store.read_candles(instrument_key, trading_date, key)
            if frame.empty or "timestamp" not in frame.columns:
                continue
            prior = frame.loc[pd.to_datetime(frame["timestamp"], errors="coerce", utc=True) <= ts_utc].copy()
            if prior.empty:
                continue
            result.append((dict(raw), prior.reset_index(drop=True)))
        return result

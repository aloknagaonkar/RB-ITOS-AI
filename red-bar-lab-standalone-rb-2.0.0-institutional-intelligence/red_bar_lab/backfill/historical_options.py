from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import json

import pandas as pd


@dataclass(frozen=True)
class HistoricalOptionsBackfillReport:
    requested_days: int
    attempted_days: int
    completed_days: int
    skipped_days: int
    failed_days: int
    rows_written: int
    date_from: str
    date_to: str
    errors: tuple[str, ...]


def _safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _select_expiry(trading_date: date, expiries: list[str]) -> str | None:
    parsed = []
    for item in expiries:
        try:
            parsed.append(date.fromisoformat(str(item)))
        except ValueError:
            continue

    # The applicable option series for a historical trading day is the first
    # known expiry on or after that date.
    candidates = sorted(exp for exp in parsed if exp >= trading_date)
    return candidates[0].isoformat() if candidates else None


def _max_pain_from_oi(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None

    strikes = pd.to_numeric(frame["strike"], errors="coerce").dropna()
    if strikes.empty:
        return None

    work = frame.copy()
    work["strike"] = pd.to_numeric(work["strike"], errors="coerce")
    work["call_oi"] = pd.to_numeric(
        work["call_oi"], errors="coerce"
    ).fillna(0.0)
    work["put_oi"] = pd.to_numeric(
        work["put_oi"], errors="coerce"
    ).fillna(0.0)

    best_strike = None
    best_pain = None
    for settlement in strikes:
        call_pain = (
            (float(settlement) - work["strike"]).clip(lower=0.0)
            * work["call_oi"]
        ).sum()
        put_pain = (
            (work["strike"] - float(settlement)).clip(lower=0.0)
            * work["put_oi"]
        ).sum()
        total = float(call_pain + put_pain)
        if best_pain is None or total < best_pain:
            best_pain = total
            best_strike = float(settlement)
    return best_strike


def summarize_historical_oi(
    *,
    instrument_key: str,
    trading_date: str,
    expiry: str,
    oi_data: dict[str, object],
    change_data: dict[str, object] | None,
    oi_artifact_path: str | None = None,
    change_artifact_path: str | None = None,
) -> dict[str, object]:
    oi_list = oi_data.get("call_put_oi_data_list") or []
    oi_rows = []
    for row in oi_list:
        if not isinstance(row, dict):
            continue
        oi_rows.append(
            {
                "strike": _safe_float(row.get("strike_price")),
                "call_oi": _safe_float(row.get("call_oi")) or 0.0,
                "put_oi": _safe_float(row.get("put_oi")) or 0.0,
            }
        )
    oi_frame = pd.DataFrame(oi_rows)

    change_by_strike = {}
    if isinstance(change_data, dict):
        for row in change_data.get("call_put_oi_data_list") or []:
            if not isinstance(row, dict):
                continue
            strike = _safe_float(row.get("strike_price"))
            if strike is None:
                continue
            change_by_strike[strike] = {
                "call_change_oi": (
                    _safe_float(row.get("call_change_oi")) or 0.0
                ),
                "put_change_oi": (
                    _safe_float(row.get("put_change_oi")) or 0.0
                ),
            }

    total_calls = _safe_float(oi_data.get("total_calls")) or 0.0
    total_puts = _safe_float(oi_data.get("total_puts")) or 0.0
    total_call_change = (
        _safe_float(change_data.get("total_call_change_oi"))
        if isinstance(change_data, dict)
        else None
    )
    total_put_change = (
        _safe_float(change_data.get("total_put_change_oi"))
        if isinstance(change_data, dict)
        else None
    )

    call_wall = None
    put_wall = None
    if not oi_frame.empty:
        if float(oi_frame["call_oi"].sum()) > 0:
            call_wall = float(
                oi_frame.loc[oi_frame["call_oi"].idxmax(), "strike"]
            )
        if float(oi_frame["put_oi"].sum()) > 0:
            put_wall = float(
                oi_frame.loc[oi_frame["put_oi"].idxmax(), "strike"]
            )

    pcr_oi = total_puts / total_calls if total_calls > 0 else None
    pcr_change = (
        total_put_change / total_call_change
        if total_put_change is not None
        and total_call_change not in (None, 0.0)
        else None
    )

    return {
        "instrument_key": instrument_key,
        "trading_date": trading_date,
        "option_expiry": expiry,
        "spot_closing_price": _safe_float(
            oi_data.get("spot_closing_price")
        ),
        "total_call_oi": total_calls,
        "total_put_oi": total_puts,
        "pcr_oi": pcr_oi,
        "total_call_oi_change": total_call_change,
        "total_put_oi_change": total_put_change,
        "pcr_oi_change": pcr_change,
        "call_wall_strike": call_wall,
        "put_wall_strike": put_wall,
        "max_pain_strike": _max_pain_from_oi(oi_frame),
        "strike_count": int(len(oi_frame)),
        "source_type": "UPSTOX_PLUS_HISTORICAL_OI_EOD",
        "entry_aligned": 0,
        "oi_artifact_path": oi_artifact_path,
        "change_artifact_path": change_artifact_path,
    }


class RedBarHistoricalOptionsBackfillService:
    def __init__(self, provider, database, settings):
        self.provider = provider
        self.database = database
        self.settings = settings

    def _available_expiries(self, instrument_key: str) -> list[str]:
        values = set()
        try:
            values.update(
                self.provider.expired_option_expiries(instrument_key)
            )
        except Exception:
            pass
        try:
            values.update(self.provider.option_expiries(instrument_key))
        except Exception:
            pass
        if not values:
            raise RuntimeError(
                "No active or historical option expiries were returned."
            )
        return sorted(values)

    def backfill_range(
        self,
        *,
        instrument_key: str,
        date_from: date,
        date_to: date,
        change_interval_days: int = 1,
        overwrite: bool = False,
        max_calendar_days: int = 186,
    ) -> HistoricalOptionsBackfillReport:
        if date_to < date_from:
            raise ValueError("date_to must be on or after date_from")

        span = (date_to - date_from).days + 1
        if span > max_calendar_days:
            raise ValueError(
                f"Backfill range is limited to {max_calendar_days} "
                "calendar days per run."
            )

        expiries = self._available_expiries(instrument_key)
        requested_days = span
        attempted = completed = skipped = failed = rows_written = 0
        errors = []

        safe_instrument = instrument_key.replace("|", "_").replace(" ", "_")
        day = date_from

        while day <= date_to:
            if day.weekday() >= 5:
                skipped += 1
                day += timedelta(days=1)
                continue

            day_str = day.isoformat()
            if (
                not overwrite
                and self.database.read_historical_option_backfill_day(
                    instrument_key,
                    day_str,
                )
            ):
                skipped += 1
                day += timedelta(days=1)
                continue

            expiry = _select_expiry(day, expiries)
            if expiry is None:
                skipped += 1
                day += timedelta(days=1)
                continue

            attempted += 1
            try:
                oi_data = self.provider.historical_oi(
                    instrument_key,
                    expiry,
                    day_str,
                )
            except Exception as exc:
                # Non-trading holidays generally surface as no-data/API errors;
                # retain the error for audit but continue the range.
                failed += 1
                errors.append(f"{day_str} OI: {exc}")
                day += timedelta(days=1)
                continue

            change_data = None
            try:
                change_data = self.provider.historical_change_oi(
                    instrument_key,
                    expiry,
                    day_str,
                    interval_days=change_interval_days,
                )
            except Exception as exc:
                # Base OI is still valuable even if Change-in-OI is unavailable.
                errors.append(f"{day_str} ChangeOI: {exc}")

            artifact_dir = (
                self.settings.artifacts_root
                / "options"
                / "historical_backfill"
                / safe_instrument
                / day_str
            )
            artifact_dir.mkdir(parents=True, exist_ok=True)

            oi_path = artifact_dir / f"{expiry}_oi.json"
            oi_path.write_text(
                json.dumps(oi_data, indent=2, default=str),
                encoding="utf-8",
            )

            change_path = None
            if change_data is not None:
                change_path = artifact_dir / f"{expiry}_change_oi.json"
                change_path.write_text(
                    json.dumps(change_data, indent=2, default=str),
                    encoding="utf-8",
                )

            summary = summarize_historical_oi(
                instrument_key=instrument_key,
                trading_date=day_str,
                expiry=expiry,
                oi_data=oi_data,
                change_data=change_data,
                oi_artifact_path=str(oi_path),
                change_artifact_path=(
                    str(change_path) if change_path else None
                ),
            )
            self.database.upsert_historical_option_backfill(summary)
            rows_written += 1
            completed += 1
            day += timedelta(days=1)

        return HistoricalOptionsBackfillReport(
            requested_days=requested_days,
            attempted_days=attempted,
            completed_days=completed,
            skipped_days=skipped,
            failed_days=failed,
            rows_written=rows_written,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            errors=tuple(errors),
        )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.options.context import (
    summarize_option_chain,
    write_option_context_csv,
)

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class OptionsCaptureReport:
    captured: int
    entry_aligned: int
    skipped: int
    expiry: str | None
    summary_path: Path | None
    chain_path: Path | None


class RedBarOptionsContextService:
    def __init__(self, provider, database, settings):
        self.provider = provider
        self.database = database
        self.settings = settings

    def available_expiries(self, instrument_key: str) -> list[str]:
        return self.provider.option_expiries(instrument_key)

    def capture_for_signal(
        self,
        *,
        instrument_key: str,
        signal: dict[str, object],
        expiry: str | None = None,
        alignment_tolerance_seconds: int = 120,
    ):
        expiries = self.available_expiries(instrument_key)
        chosen_expiry = expiry or expiries[0]

        records = self.provider.option_chain(
            instrument_key,
            chosen_expiry,
        )
        chain = self.provider.option_chain_dataframe(records)

        snapshot_ts = datetime.now(IST)
        safe_instrument = instrument_key.replace("|", "_")
        signal_id = str(signal.get("signal_id") or "unknown")
        stamp = snapshot_ts.strftime("%Y%m%d_%H%M%S")

        chain_path = (
            self.settings.artifacts_root
            / "options"
            / safe_instrument
            / str(signal.get("trading_date"))
            / f"{signal_id}_{stamp}_chain.csv"
        )
        chain_path.parent.mkdir(parents=True, exist_ok=True)
        chain.to_csv(chain_path, index=False)

        row = summarize_option_chain(
            signal=signal,
            instrument_key=instrument_key,
            expiry=chosen_expiry,
            chain=chain,
            snapshot_timestamp=snapshot_ts,
            alignment_tolerance_seconds=alignment_tolerance_seconds,
            chain_artifact_path=str(chain_path),
        )
        existing_row = self.database.read_option_context_by_signal(
            str(signal.get("signal_id"))
        )
        if not (
            existing_row
            and bool(existing_row.get("entry_aligned"))
            and not bool(row.get("entry_aligned"))
        ):
            self.database.upsert_option_context_snapshots([row])
        else:
            row = existing_row

        summary_path = (
            self.settings.artifacts_root
            / "options"
            / safe_instrument
            / f"option_context_{signal.get('trading_date')}.csv"
        )
        existing = self.database.read_option_context_snapshots(
            instrument_key,
            str(signal.get("trading_date")),
            str(signal.get("trading_date")),
        )
        write_option_context_csv(existing, summary_path)
        return row, chain


    def capture_recent_missing_signals(
        self,
        *,
        instrument_key: str,
        trading_date: str,
        alignment_tolerance_seconds: int = 120,
        expiry: str | None = None,
    ) -> OptionsCaptureReport:
        """Capture only newly confirmed signals that are still entry-alignable.

        This method performs no Upstox option-chain call when there is no recent
        signal requiring a snapshot.
        """
        now = pd.Timestamp(datetime.now(IST))
        signals = self.database.read_signal_attempts(
            instrument_key,
            trading_date,
        )

        candidates = []
        for signal in signals:
            if (
                not signal.get("signal_id")
                or not signal.get("confirmation_timestamp")
                or signal.get("state") != "ACTIVE"
            ):
                continue

            entry_ts = pd.Timestamp(signal["confirmation_timestamp"])
            if entry_ts.tzinfo is None:
                entry_ts = entry_ts.tz_localize("Asia/Kolkata")
            else:
                entry_ts = entry_ts.tz_convert("Asia/Kolkata")

            delay = (now - entry_ts).total_seconds()
            if delay < 0 or delay > alignment_tolerance_seconds:
                continue

            existing = self.database.read_option_context_by_signal(
                str(signal["signal_id"])
            )
            if existing and bool(existing.get("entry_aligned")):
                continue

            candidates.append(signal)

        if not candidates:
            return OptionsCaptureReport(
                captured=0,
                entry_aligned=0,
                skipped=0,
                expiry=expiry,
                summary_path=None,
                chain_path=None,
            )

        expiries = self.available_expiries(instrument_key)
        chosen_expiry = expiry or expiries[0]
        records = self.provider.option_chain(
            instrument_key,
            chosen_expiry,
        )
        chain = self.provider.option_chain_dataframe(records)
        snapshot_ts = datetime.now(IST)

        safe_instrument = instrument_key.replace("|", "_")
        stamp = snapshot_ts.strftime("%Y%m%d_%H%M%S")
        chain_path = (
            self.settings.artifacts_root
            / "options"
            / safe_instrument
            / trading_date
            / f"chain_{stamp}.csv"
        )
        chain_path.parent.mkdir(parents=True, exist_ok=True)
        chain.to_csv(chain_path, index=False)

        rows = []
        skipped = 0
        for signal in candidates:
            try:
                rows.append(
                    summarize_option_chain(
                        signal=signal,
                        instrument_key=instrument_key,
                        expiry=chosen_expiry,
                        chain=chain,
                        snapshot_timestamp=snapshot_ts,
                        alignment_tolerance_seconds=alignment_tolerance_seconds,
                        chain_artifact_path=str(chain_path),
                    )
                )
            except (ValueError, TypeError, KeyError):
                skipped += 1

        self.database.upsert_option_context_snapshots(rows)

        summary_path = (
            self.settings.artifacts_root
            / "options"
            / safe_instrument
            / f"option_context_{trading_date}.csv"
        )
        write_option_context_csv(
            self.database.read_option_context_snapshots(
                instrument_key,
                trading_date,
                trading_date,
            ),
            summary_path,
        )

        return OptionsCaptureReport(
            captured=len(rows),
            entry_aligned=sum(
                int(bool(row.get("entry_aligned"))) for row in rows
            ),
            skipped=skipped,
            expiry=chosen_expiry,
            summary_path=summary_path,
            chain_path=chain_path,
        )

    def capture_current_confirmed_signals(
        self,
        *,
        instrument_key: str,
        trading_date: str,
        expiry: str | None = None,
        alignment_tolerance_seconds: int = 120,
    ) -> OptionsCaptureReport:
        signals = self.database.read_signal_attempts(
            instrument_key,
            trading_date,
        )
        confirmed = [
            row for row in signals
            if row.get("signal_id")
            and row.get("confirmation_timestamp")
            and row.get("state") == "ACTIVE"
        ]

        if not confirmed:
            return OptionsCaptureReport(
                0, 0, 0, expiry, None, None
            )

        expiries = self.available_expiries(instrument_key)
        chosen_expiry = expiry or expiries[0]
        records = self.provider.option_chain(
            instrument_key,
            chosen_expiry,
        )
        chain = self.provider.option_chain_dataframe(records)
        snapshot_ts = datetime.now(IST)

        safe_instrument = instrument_key.replace("|", "_")
        stamp = snapshot_ts.strftime("%Y%m%d_%H%M%S")
        chain_path = (
            self.settings.artifacts_root
            / "options"
            / safe_instrument
            / trading_date
            / f"chain_{stamp}.csv"
        )
        chain_path.parent.mkdir(parents=True, exist_ok=True)
        chain.to_csv(chain_path, index=False)

        rows = []
        skipped = 0
        for signal in confirmed:
            try:
                rows.append(
                    summarize_option_chain(
                        signal=signal,
                        instrument_key=instrument_key,
                        expiry=chosen_expiry,
                        chain=chain,
                        snapshot_timestamp=snapshot_ts,
                        alignment_tolerance_seconds=alignment_tolerance_seconds,
                        chain_artifact_path=str(chain_path),
                    )
                )
            except (ValueError, TypeError, KeyError):
                skipped += 1

        protected_rows = []
        for row in rows:
            existing_row = self.database.read_option_context_by_signal(
                str(row.get("signal_id"))
            )
            if (
                existing_row
                and bool(existing_row.get("entry_aligned"))
                and not bool(row.get("entry_aligned"))
            ):
                protected_rows.append(existing_row)
            else:
                protected_rows.append(row)

        self.database.upsert_option_context_snapshots(protected_rows)
        rows = protected_rows

        summary_path = (
            self.settings.artifacts_root
            / "options"
            / safe_instrument
            / f"option_context_{trading_date}.csv"
        )
        write_option_context_csv(
            self.database.read_option_context_snapshots(
                instrument_key,
                trading_date,
                trading_date,
            ),
            summary_path,
        )

        return OptionsCaptureReport(
            captured=len(rows),
            entry_aligned=sum(
                int(bool(row.get("entry_aligned"))) for row in rows
            ),
            skipped=skipped,
            expiry=chosen_expiry,
            summary_path=summary_path,
            chain_path=chain_path,
        )

    def import_context_frame(self, frame: pd.DataFrame) -> int:
        required = {
            "signal_id",
            "instrument_key",
            "trading_date",
            "entry_timestamp",
            "option_snapshot_timestamp",
        }
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(
                "Options context import is missing columns: "
                + ", ".join(missing)
            )
        rows = frame.to_dict(orient="records")
        return self.database.upsert_option_context_snapshots(rows)

    def import_context_csv(self, path: Path) -> int:
        return self.import_context_frame(pd.read_csv(path))

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

from red_bar_lab.execution.bundles.bundle_model import StrategySignalBundle, infer_strategy_id


STRATEGY_FOLDERS = {
    "RED_BAR": "red_bar",
    "DIRECTIONAL_REGIME": "directional_regime",
    "RSI_EXTREME_REVERSAL": "rsi_extreme_reversal",
}


def safe_instrument_name(instrument_key: str) -> str:
    return instrument_key.replace("|", "_").replace(" ", "_").replace("/", "_").replace("\\", "_")


class StrategyBundleStore:
    """Append-once strategy-scoped JSONL storage.

    UI pages must use read methods only. Background producers explicitly call append_once.
    """

    def __init__(self, runs_root: str | Path):
        self.root = Path(runs_root) / "strategy_bundles"

    def path_for(self, strategy_id: str, instrument_key: str) -> Path:
        folder = STRATEGY_FOLDERS[strategy_id]
        return self.root / folder / f"{safe_instrument_name(instrument_key)}.jsonl"

    def read(self, strategy_id: str, instrument_key: str) -> list[dict[str, object]]:
        path = self.path_for(strategy_id, instrument_key)
        if not path.exists():
            return []
        rows: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(row, dict) and infer_strategy_id(row) == strategy_id:
                rows.append(row)
        return rows

    def append_once(self, bundle: StrategySignalBundle) -> bool:
        path = self.path_for(bundle.strategy_id, bundle.instrument_key)
        existing = self.read(bundle.strategy_id, bundle.instrument_key)
        identity = bundle.canonical_event_identity or bundle.bundle_id
        if any(
            str(row.get("canonical_event_identity") or row.get("bundle_id") or "") == identity
            for row in existing
        ):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(bundle.as_record(), separators=(",", ":"), default=str) + "\n")
        return True


def latest_bundle(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    values = [dict(row) for row in rows]
    if not values:
        return {}
    return max(values, key=lambda row: str(row.get("detected_at") or ""))

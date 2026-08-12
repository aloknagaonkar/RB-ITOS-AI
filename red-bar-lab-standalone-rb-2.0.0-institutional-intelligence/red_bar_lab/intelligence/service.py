from dataclasses import dataclass
from pathlib import Path

from red_bar_lab.features.store import RedBarFeatureStore

from red_bar_lab.intelligence.dataset import (
    build_training_rows,
    label_frame,
    prediction_feature_frame,
    validate_no_lookahead_features,
    write_training_dataset,
)


@dataclass(frozen=True)
class IntelligenceDatasetReport:
    rows: int
    features: int
    labels: int
    output_path: Path


class RedBarIntelligenceDatasetService:
    def __init__(self, database, settings):
        self.database = database
        self.settings = settings

    def build_for_range(self, instrument_key, date_from, date_to):
        signals = self.database.read_signal_attempts_range(
            instrument_key, date_from, date_to
        )
        trades = self.database.read_paper_trade_outcomes_range(
            instrument_key, date_from, date_to
        )
        feature_store = RedBarFeatureStore(self.database)
        feature_rows = feature_store.rows_for_range(
            instrument_key,
            date_from,
            date_to,
        )
        rows = build_training_rows(
            signals,
            trades,
            feature_rows=feature_rows,
        )
        features = prediction_feature_frame(rows)
        labels = label_frame(rows)
        validate_no_lookahead_features(features.columns)

        output = (
            self.settings.artifacts_root
            / "intelligence"
            / instrument_key.replace("|", "_")
            / f"training_{date_from}_{date_to}.csv"
        )
        write_training_dataset(rows, output)
        return rows, IntelligenceDatasetReport(
            len(rows), len(features.columns), len(labels.columns), output
        )

from red_bar_lab.features.store import RedBarFeatureStore


class FakeDB:
    def read_market_context_by_signal(self, signal_id):
        return {"signal_id": signal_id, "gap_pct": 0.5}

    def read_volume_structure_by_signal(self, signal_id):
        return {"signal_id": signal_id, "relative_volume_20m": 1.8}

    def read_option_context_by_signal(self, signal_id):
        return {
            "signal_id": signal_id,
            "entry_aligned": 0,
            "pcr_oi": 1.25,
            "atm_strike": 25000,
        }


def test_feature_store_blocks_non_aligned_options_from_ai_features():
    store = RedBarFeatureStore(FakeDB())
    features = store.get_features("RB-X")["flat"]

    assert features["gap_pct"] == 0.5
    assert features["relative_volume_20m"] == 1.8
    assert features["options_entry_aligned"] == 0
    assert features["pcr_oi"] is None
    assert features["atm_strike"] is None


class AlignedDB(FakeDB):
    def read_option_context_by_signal(self, signal_id):
        return {
            "signal_id": signal_id,
            "entry_aligned": 1,
            "pcr_oi": 1.25,
            "atm_strike": 25000,
        }


def test_feature_store_exposes_entry_aligned_options():
    store = RedBarFeatureStore(AlignedDB())
    features = store.get_features("RB-X")["flat"]

    assert features["options_entry_aligned"] == 1
    assert features["pcr_oi"] == 1.25
    assert features["atm_strike"] == 25000

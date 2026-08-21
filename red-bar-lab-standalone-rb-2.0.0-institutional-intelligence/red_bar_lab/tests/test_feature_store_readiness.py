from red_bar_lab.services.feature_store_readiness import (
    calculate_feature_store_readiness,
)


def test_core_and_hybrid_counts_use_signal_id_intersections():
    result = calculate_feature_store_readiness(
        confirmed_signal_ids=["RBV2-1", "RBV2-2", "RBV2-3"],
        market_ready_ids=["RBV2-1", "RBV2-2"],
        volume_ready_ids=["RBV2-2", "RBV2-3"],
        option_ready_ids=["RBV2-1", "RBV2-2", "RBV2-3"],
    )
    assert result.core_feature_ids == ("RBV2-2",)
    assert result.hybrid_feature_ids == ("RBV2-2",)
    assert result.core_feature_count == 1
    assert result.hybrid_feature_count == 1


def test_unconfirmed_ids_do_not_enter_feature_counts():
    result = calculate_feature_store_readiness(
        confirmed_signal_ids=["RBV2-1"],
        market_ready_ids=["RBV2-1", "LEGACY-1"],
        volume_ready_ids=["RBV2-1", "LEGACY-1"],
        option_ready_ids=["RBV2-1", "LEGACY-1"],
    )
    assert result.core_feature_ids == ("RBV2-1",)
    assert result.hybrid_feature_ids == ("RBV2-1",)

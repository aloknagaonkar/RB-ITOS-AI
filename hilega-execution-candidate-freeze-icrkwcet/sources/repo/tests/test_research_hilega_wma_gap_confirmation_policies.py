from scripts.research_hilega_wma_gap_confirmation_policies import (
    select_current,
    select_early_reconfirmation,
    select_persistence,
)


def pair(armed, confirmed, latency):
    return {
        "armed_timestamp": armed,
        "confirmation_timestamp": confirmed,
        "actionable_latency_minutes": latency,
    }


def test_current_uses_first_pair():
    pairs = [pair("09:25", "09:26", 1), pair("09:26", "09:27", 2)]
    assert select_current(pairs) is pairs[0]


def test_persistence_requires_adjacent_full_passes():
    pairs = [
        pair("09:25", "09:26", 1),
        pair("09:27", "09:28", 3),
        pair("09:28", "09:29", 4),
    ]
    assert select_persistence(pairs) is pairs[2]


def test_persistence_denies_isolated_passes():
    pairs = [pair("09:25", "09:26", 1), pair("09:27", "09:28", 3)]
    assert select_persistence(pairs) is None


def test_early_confirmation_requires_t3_t5_reconfirmation():
    pairs = [
        pair("09:25", "09:26", 1),
        pair("09:28", "09:29", 4),
    ]
    assert select_early_reconfirmation(pairs) is pairs[1]


def test_early_confirmation_without_reconfirmation_is_denied():
    assert select_early_reconfirmation([pair("09:25", "09:26", 1)]) is None


def test_first_confirmation_after_t2_is_used_directly():
    pairs = [pair("09:28", "09:29", 4)]
    assert select_early_reconfirmation(pairs) is pairs[0]

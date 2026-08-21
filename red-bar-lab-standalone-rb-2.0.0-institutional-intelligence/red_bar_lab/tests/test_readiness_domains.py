from red_bar_lab.services.readiness_domains import (
    build_readiness_domains,
    independent_path_ready,
    red_bar_v2_path_ready,
)


def test_red_bar_v2_blocker_does_not_block_independent_path():
    domains = build_readiness_domains(
        red_bar_v2_reasons=["REFERENCE_NOT_FOUND"],
    )
    assert independent_path_ready(domains) is True
    assert red_bar_v2_path_ready(domains) is False


def test_market_data_blocker_blocks_both_observational_paths():
    domains = build_readiness_domains(
        market_data_reasons=["OPTION_SNAPSHOT_STALE"],
    )
    assert independent_path_ready(domains) is False
    assert red_bar_v2_path_ready(domains) is False


def test_execution_readiness_is_not_inferred_from_diagnostics():
    domains = build_readiness_domains(
        execution_reasons=["EXECUTION_POLICY_NOT_APPROVED"],
    )
    assert domains.market_data_readiness.status == "READY"
    assert domains.independent_strategy_readiness.status == "READY"
    assert domains.execution_readiness.status == "BLOCKED"
    assert domains.authority == "OBSERVATIONAL_ONLY"

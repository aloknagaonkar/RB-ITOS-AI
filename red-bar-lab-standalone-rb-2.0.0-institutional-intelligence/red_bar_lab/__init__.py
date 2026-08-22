from __future__ import annotations

# Additive package-level hardening hooks. These preserve stable source modules
# while installing reversible compatibility and evidence-quality boundaries.
from red_bar_lab.brokers.missing_data_option_chain import (
    install as _install_missing_data_option_chain,
)
from red_bar_lab.services.market_evidence_quality_patch import (
    install as _install_market_evidence_quality,
)

_install_missing_data_option_chain()
_install_market_evidence_quality()

__all__: list[str] = []

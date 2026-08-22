from __future__ import annotations

# Additive package-level hardening hooks.  These preserve the stable source
# modules while installing truthful compatibility boundaries at import time.
from red_bar_lab.brokers.missing_data_option_chain import (
    install as _install_missing_data_option_chain,
)

_install_missing_data_option_chain()

__all__: list[str] = []

from __future__ import annotations

"""Centralized additive runtime hardening installation.

The installer keeps compatibility hooks in one place and adds a bounded retry
policy only for idempotent broker GET requests. POST/order operations are not
retried here.
"""

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from red_bar_lab.brokers.missing_data_option_chain import (
    install as _install_missing_data_option_chain,
)
from red_bar_lab.services.market_evidence_quality_patch import (
    install as _install_market_evidence_quality,
)

_INSTALLED = False


def _install_upstox_get_retry_policy() -> None:
    from red_bar_lab.brokers.upstox_client import UpstoxClient

    if getattr(UpstoxClient, "_rb_get_retry_policy_installed", False):
        return

    original_init = UpstoxClient.__init__

    def hardened_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        mount = getattr(self.session, "mount", None)
        if not callable(mount):
            return
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        mount("https://", adapter)
        mount("http://", adapter)
        self.get_retry_policy = {
            "total": 3,
            "backoff_factor": 0.5,
            "status_forcelist": (429, 502, 503, 504),
            "allowed_methods": ("GET", "HEAD", "OPTIONS"),
            "respect_retry_after_header": True,
        }

    UpstoxClient.__init__ = hardened_init
    UpstoxClient._rb_get_retry_policy_installed = True


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_missing_data_option_chain()
    _install_market_evidence_quality()
    _install_upstox_get_retry_policy()
    _INSTALLED = True


__all__ = ["install"]

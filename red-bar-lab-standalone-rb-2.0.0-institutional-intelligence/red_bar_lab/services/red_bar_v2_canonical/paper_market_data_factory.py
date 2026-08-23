from __future__ import annotations

from typing import Mapping

from red_bar_lab.config import RedBarSettings, UNDERLYINGS

from .paper_market_data import (
    PaperCanaryMarketData,
    PaperMarketDataConfigurationError,
)


def build_paper_canary_market_data(
    *,
    settings: RedBarSettings,
    environment: Mapping[str, str],
) -> PaperCanaryMarketData:
    provider = settings.red_bar_v2_paper_canary_market_data_provider
    if provider == "ZERODHA":
        api_key = str(environment.get("ZERODHA_API_KEY") or "").strip()
        access_token = str(environment.get("ZERODHA_ACCESS_TOKEN") or "").strip()
        if not api_key or not access_token:
            raise PaperMarketDataConfigurationError("ZERODHA_CONFIGURATION_MISSING")
        from red_bar_lab.brokers.zerodha_client import ZerodhaKiteClient
        from .zerodha_paper_market_data import ZerodhaPaperCanaryMarketData

        return ZerodhaPaperCanaryMarketData(
            ZerodhaKiteClient(api_key, access_token),
            maximum_quote_age_seconds=settings.red_bar_v2_paper_canary_max_bundle_age_seconds,
        )
    if provider == "UPSTOX":
        access_token = str(environment.get("UPSTOX_ACCESS_TOKEN") or "").strip()
        if not access_token:
            raise PaperMarketDataConfigurationError("UPSTOX_CONFIGURATION_MISSING")
        from red_bar_lab.brokers.upstox_client import UpstoxClient
        from .upstox_paper_market_data import UpstoxPaperCanaryMarketData

        return UpstoxPaperCanaryMarketData(
            UpstoxClient(access_token),
            underlying_keys=UNDERLYINGS,
            maximum_quote_age_seconds=settings.red_bar_v2_paper_canary_max_bundle_age_seconds,
        )
    reason = (
        "MARKET_DATA_PROVIDER_UNCONFIGURED"
        if provider == "UNCONFIGURED"
        else "MARKET_DATA_PROVIDER_INVALID"
    )
    raise PaperMarketDataConfigurationError(reason)

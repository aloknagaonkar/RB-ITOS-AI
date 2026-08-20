from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from red_bar_lab.brokers.upstox_client import UpstoxAPIError


@dataclass
class UpstoxInstrumentSearchTransport:
    """Read-only transport for the Upstox Instrument Search API.

    This is intentionally separate from order execution. It only discovers
    instrument-master records and never sends broker orders.
    """

    access_token: str
    timeout: int = 20
    session: requests.Session | None = None

    BASE_URL = "https://api.upstox.com/v2"

    def __post_init__(self) -> None:
        self.access_token = str(self.access_token or "").strip()
        if not self.access_token:
            raise ValueError("Upstox access token is required.")
        if self.session is None:
            self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    @staticmethod
    def _raise_for_api_error(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            payload = response.json()
            errors = payload.get("errors") or []
            message = (
                errors[0].get("message")
                if errors and isinstance(errors[0], dict)
                else payload.get("message")
            )
        except (ValueError, AttributeError):
            message = response.text
        raise UpstoxAPIError(
            f"HTTP {response.status_code}: {message or 'Instrument search failed'}"
        )

    def search_instruments(
        self,
        *,
        query: str,
        exchanges: str = "ALL",
        segments: str = "ALL",
        instrument_types: str | None = None,
        expiry: str | None = None,
        atm_offset: int | None = None,
        page_number: int = 1,
        records: int = 10,
    ) -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            raise ValueError("Instrument search query is required.")
        if len(text) > 50:
            raise ValueError("Instrument search query must be at most 50 characters.")

        page = int(page_number)
        page_size = int(records)
        if page < 1:
            raise ValueError("page_number must be at least 1.")
        if page_size < 1 or page_size > 30:
            raise ValueError("records must be between 1 and 30.")

        params: dict[str, Any] = {
            "query": text,
            "exchanges": str(exchanges or "ALL").strip(),
            "segments": str(segments or "ALL").strip(),
            "page_number": page,
            "records": page_size,
        }
        if instrument_types:
            params["instrument_types"] = str(instrument_types).strip()
        if expiry:
            params["expiry"] = str(expiry).strip()
        if atm_offset is not None:
            params["atm_offset"] = int(atm_offset)

        assert self.session is not None
        response = self.session.get(
            f"{self.BASE_URL}/instruments/search",
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstoxAPIError("Malformed instrument-search response.") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise UpstoxAPIError("Malformed instrument-search response.")
        return [dict(row) for row in data if isinstance(row, dict)]

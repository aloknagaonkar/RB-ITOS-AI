"""Installed GET-only account capture as a staged provider."""
from copy import deepcopy

from market_lab.hilega_production_account_adapter_v1 import capture, Client


def make_capture_provider(client, pin, *, clock):
    if type(client) is not Client:
        raise ValueError("FIXED_GET_ONLY_CLIENT_REQUIRED")
    pinned = deepcopy(pin)

    def provide():
        return capture(client, pinned, clock=clock)

    return provide


"""Closed live boundary: no credentials, HTTP calls or execution attempts."""
from contextlib import contextmanager
from unittest.mock import Mock, patch
import unittest

from market_lab.hilega_execution_port_v1 import adapter as a


class EventOnlyStore:
    """In-memory spy; rejects every execution-table query."""
    mode = "LIVE_CLOSED"

    def __init__(self):
        self.events = []
        self.transactions = 0

    @contextmanager
    def tx(self):
        self.transactions += 1
        yield self

    def execute(self, *args, **kwargs):
        raise AssertionError("Closed gate reached execution SQL")

    def event(self, db, name, **fields):
        assert db is self
        self.events.append((name, fields))


class ClosedLiveBoundary(unittest.TestCase):
    def test_clearance_always_closed(self):
        with self.assertRaisesRegex(
            a.GateClosed, "^PRODUCTION_MUTATIONS_CLOSED_IN_CODE$"
        ):
            a.require_live_clearance()

    def test_transport_check_closed(self):
        token = Mock(side_effect=AssertionError("Token must not be requested"))
        with self.assertRaises(a.GateClosed):
            a.HttpTransport(token).check()
        token.assert_not_called()

    def test_transport_send_never_fetches_token_or_opens_http(self):
        token = Mock(side_effect=AssertionError("Token must not be requested"))
        transport = a.HttpTransport(token)
        wire = {
            "method": "POST",
            "host": "api-hft.upstox.com",
            "path": "/v3/order/place",
            "body": {},
        }
        with patch.object(a, "build_opener") as opener:
            with self.assertRaises(a.GateClosed):
                transport.send("fixture-attempt", wire)
            opener.assert_not_called()
        token.assert_not_called()

    def check_adapter_operation(self, operation):
        store = EventOnlyStore()
        token = Mock(side_effect=AssertionError("Token must not be requested"))
        transport = a.HttpTransport(token)
        adapter = a.Adapter(store, transport)
        with patch.object(transport, "send") as send:
            result = getattr(adapter, operation)("fixture-request")
            send.assert_not_called()

        self.assertEqual(
            result["status"], "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
        )
        self.assertIs(result["orders_sent"], False)
        self.assertIs(result["production_execution_enabled"], False)
        self.assertEqual(store.transactions, 1)
        self.assertEqual(len(store.events), 1)
        self.assertEqual(store.events[0][0], "PRODUCTION_GATE_REFUSED")
        self.assertEqual(
            store.events[0][1]["operation"],
            "PLACE" if operation == "submit" else "CANCEL",
        )
        token.assert_not_called()

    def test_submit_refused_before_attempt_creation(self):
        self.check_adapter_operation("submit")

    def test_cancel_refused_before_attempt_creation(self):
        self.check_adapter_operation("cancel")

    def test_adapter_has_no_reservation_release_authority(self):
        adapter = a.Adapter(EventOnlyStore(), a.HttpTransport(Mock()))
        with self.assertRaisesRegex(
            a.Blocked, "^ADAPTER_HAS_NO_RELEASE_AUTHORITY$"
        ):
            adapter.release_reservation()


if __name__ == "__main__":
    unittest.main()

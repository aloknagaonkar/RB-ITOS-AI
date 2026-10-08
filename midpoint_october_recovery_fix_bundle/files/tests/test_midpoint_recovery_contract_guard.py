from datetime import date
from types import SimpleNamespace
import pytest
from scripts import materialize_midpoint_forward_market_data as m


def test_october_never_requires_september_contract(monkeypatch):
    monkeypatch.setattr(m, "resolve_expired_future", lambda *a: pytest.fail("September lookup for October"))
    assert m.resolve_required_september_future(object(), [date(2026, 10, 6), date(2026, 10, 7)]) is None


def test_september_preserves_contract_guard(monkeypatch):
    monkeypatch.setattr(m, "resolve_expired_future", lambda *a: None)
    with pytest.raises(RuntimeError, match="SEPTEMBER_29"):
        m.resolve_required_september_future(object(), [date(2026, 9, 29)])


def test_mixed_dates_resolve_using_september_day(monkeypatch):
    seen = []
    contract = SimpleNamespace(expiry=date(2026, 9, 29))
    def resolve(client, day, expiries):
        seen.append(day)
        return contract
    monkeypatch.setattr(m, "resolve_expired_future", resolve)
    assert m.resolve_required_september_future(object(), [date(2026, 10, 6), date(2026, 9, 29)]) is contract
    assert seen == [date(2026, 9, 29)]


def test_wrong_september_expiry_fails_closed(monkeypatch):
    monkeypatch.setattr(m, "resolve_expired_future", lambda *a: SimpleNamespace(expiry=date(2026, 10, 27)))
    with pytest.raises(AssertionError, match="SEPTEMBER_EXPIRY_MISMATCH"):
        m.resolve_required_september_future(object(), [date(2026, 9, 29)])

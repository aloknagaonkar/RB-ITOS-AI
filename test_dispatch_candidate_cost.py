"""Independent candidate-cost rejection tests; no DB or broker access."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

path = Path.home() / "dispatch_precondition_review.py"
spec = importlib.util.spec_from_file_location("cost_review_target", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def inputs():
    return [
        dict(premium_cents=650000, fee_buffer_cents=10000,
             budget_cents=660000),
        dict(premium_cents=650000, fee_buffer_cents=10000,
             held_cents=660000, cash_cap_cents=660000),
        dict(order_type="LIMIT", transaction_type="BUY",
             price=100, quantity=65),
        dict(instrument_key="NSE_FO|12345",
             underlying_key="NSE_INDEX|Nifty 50",
             segment="NSE_FO", exchange="NSE",
             instrument_type="CE", lot_size=65, tick_size=5),
        "100",
    ]


def test_exact_reserved_budget():
    values = inputs()
    original = deepcopy(values)
    assert module.verify_candidate_cost(*values) == dict(
        premium_paise=650000, buffer_paise=10000, budget_paise=660000)
    assert values == original


@pytest.mark.parametrize("case", [
    "changed_price", "off_grid", "quantity", "premium",
    "boolean_buffer", "zero_buffer", "budget",
    "reservation_buffer", "short_hold", "short_cap",
])
def test_changed_cost_rejected(case):
    values = inputs()
    candidate, reservation, body, contract, ask = values
    if case == "changed_price":
        body["price"] = 101
    elif case == "off_grid":
        body["price"] = "100.01"
        values[4] = "100.01"
    elif case == "quantity":
        body["quantity"] = 130
    elif case == "premium":
        candidate["premium_cents"] += 1
    elif case == "boolean_buffer":
        candidate["fee_buffer_cents"] = True
    elif case == "zero_buffer":
        candidate["fee_buffer_cents"] = 0
    elif case == "budget":
        candidate["budget_cents"] -= 1
    elif case == "reservation_buffer":
        reservation["fee_buffer_cents"] += 1
    elif case == "short_hold":
        reservation["held_cents"] -= 1
    else:
        reservation["cash_cap_cents"] -= 1

    with pytest.raises(ValueError):
        module.verify_candidate_cost(*values)
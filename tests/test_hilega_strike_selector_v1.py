from datetime import datetime, timedelta

from market_lab.hilega_strike_selector_v1 import StrikePolicy, rank_strikes


NOW = datetime.fromisoformat("2026-10-14T12:00:05+05:30")


def policy():
    return StrikePolicy(version="research-approved-v1", strategy_version="sample-version", approved=True,
                        ranked_ce_roles=(-1, 0, -2, 1, 2), ranked_pe_roles=(1, 0, 2, -1, -2),
                        max_spread_pct=2, min_bid_quantity=65, min_ask_quantity=65,
                        min_volume=100, max_signal_age_seconds=30, max_quote_age_seconds=10,
                        max_one_lot_premium_rupees=20000)


def candidates(side="CE"):
    return [dict(role=role, option_type=side, expiry="2026-10-20",
                 instrument_key=f"{side}{role}", lot_size=65,
                 bid_price=99, ask_price=100, bid_quantity=650, ask_quantity=650,
                 volume=1000, quote_time=NOW.isoformat()) for role in (-2, -1, 0, 1, 2)]


def rank(rows, direction="BULLISH", evaluated_at=NOW):
    return rank_strikes(policy=policy(), strategy_version="sample-version", direction=direction,
                        signal_time=(NOW - timedelta(seconds=5)).isoformat(),
                        evaluated_at=evaluated_at.isoformat(), candidates=rows)


def test_ranked_ce_uses_first_tradeable_role_and_preserves_rejections():
    rows = candidates()
    rows[1]["ask_price"] = 120
    result = rank(rows)
    assert result["status"] == "SELECTED"
    assert result["selected"]["role"] == 0
    assert result["candidates"][0]["rejection_reasons"] == ["SPREAD_TOO_WIDE"]
    assert result["candidates"][0]["rank"] == 1


def test_ranked_pe_order_and_no_trade_on_stale_signal():
    result = rank(candidates("PE"), direction="BEARISH")
    assert result["selected"]["role"] == 1
    stale = rank(candidates("PE"), direction="BEARISH", evaluated_at=NOW + timedelta(seconds=31))
    assert stale["status"] == "NO_TRADE"
    assert stale["reason"] == "SIGNAL_STALE_OR_FUTURE"


def test_missing_quote_data_never_selects_candidate():
    rows = candidates()
    for row in rows:
        row.pop("quote_time")
    result = rank(rows)
    assert result["status"] == "NO_TRADE"
    assert all(not row["eligible"] for row in result["candidates"])

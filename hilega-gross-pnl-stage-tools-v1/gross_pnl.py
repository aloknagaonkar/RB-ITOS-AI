"""Fixture-only exact gross arithmetic; aggregate fees never become strategy fees."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hmac
from bridge import ident, validate_account_rows
from fee_report import assess_response, query
from risk_evidence_audit import need
from signature_checks import aware, day, sign


def authenticated(value,pin):
    need(isinstance(value,dict),"SIGNED_OBJECT_REQUIRED")
    payload=dict(value);signature=payload.pop("signature",None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(payload,pin),signature),
         "EVIDENCE_SIGNATURE_INVALID")
    need(value.get("account_scope")==pin["scope"],"EVIDENCE_ACCOUNT_SCOPE_MISMATCH")
    return payload


def positive_price(value):
    need(type(value) in (str,int,float,Decimal),"FILL_PRICE_INVALID")
    try:number=Decimal(str(value))
    except InvalidOperation:raise ValueError("FILL_PRICE_INVALID") from None
    need(number.is_finite() and number>0,"FILL_PRICE_INVALID")
    return Fraction(number)


def exact_paise(value):
    paise=value*100
    return dict(integer_paise=paise.numerator if paise.denominator==1 else None,
                numerator=paise.numerator,denominator=paise.denominator)


def preview_fixture_pnl(state,pin,*,as_of,fee_capture=None):
    need(pin["scope"].startswith("FIXTURE:"),"FIXTURE_ACCOUNT_REQUIRED")
    value=authenticated(state,pin)
    now=aware(as_of);observed=aware(value["observed_at"])
    need(0<=(now-observed).total_seconds()<=30 and day(now)==day(observed),
         "FILL_STATE_STALE_FUTURE_OR_WRONG_SESSION")
    need(value.get("production_execution_enabled") is False
         and value.get("reservation_release_permission") is False,
         "FILL_STATE_AUTHORITY_FORBIDDEN")
    orders=value["orders"];fills=value["fills"]
    need(isinstance(orders,dict) and isinstance(fills,dict) and len(orders)==2,
         "SINGLE_ENTRY_EXIT_LIFECYCLE_REQUIRED")
    need({o["side"] for o in orders.values()}=={"BUY","SELL"},
         "ONE_BUY_AND_ONE_SELL_ORDER_REQUIRED")
    need(len({(o["instrument"],o["product"]) for o in orders.values()})==1,
         "LIFECYCLE_CONTRACT_MISMATCH")
    validate_account_rows(dict(orders=list(orders.values()),trades=list(fills.values()),
        positions=[],session_date=day(now),completed_at=as_of))
    need(type(value["remaining_quantity"]) is int and value["remaining_quantity"]>=0,
         "REMAINING_QUANTITY_INVALID")
    totals={oid:0 for oid in orders}
    timeline=[];seen=set()
    for oid,o in orders.items():
        need(o["order_id"]==oid,"ORDER_ID_MISMATCH")
        ident(oid)
        need(type(o["quantity"]) is int and o["quantity"]>0
             and type(o["filled"]) is int and 0<=o["filled"]<=o["quantity"],
             "ORDER_QUANTITY_INVALID")
    for key,f in fills.items():
        oid,tid=ident(f["order_id"]),ident(f["trade_id"])
        need(oid in orders and (oid,tid) not in seen,"FILL_ORDER_OR_ID_INVALID")
        seen.add((oid,tid))
        need(key==oid+"|"+tid,"FILL_KEY_MISMATCH")
        o=orders[oid]
        need(all(f[k]==o[k] for k in ("instrument","product","side")),
             "FILL_CONTRACT_MISMATCH")
        q=f["quantity"]
        need(type(q) is int and q>0,"FILL_QUANTITY_INVALID")
        at=aware(f["filled_at"])
        need(aware(o["placed_at"])<=at<=now and day(at)==day(now),
             "FILL_TIME_INVALID")
        timeline.append((at,f,positive_price(f["price"])))
        totals[oid]+=q
    need(all(totals[oid]==o["filled"] for oid,o in orders.items()),
         "ORDER_TRADE_FILL_TOTAL_MISMATCH")
    need(any(o["side"]=="BUY" and o["filled"]>0 for o in orders.values()),
         "NO_EXECUTION_BASELINE_IS_NOT_ZERO_PNL")
    buys={at for at,f,p in timeline if f["side"]=="BUY"}
    sells={at for at,f,p in timeline if f["side"]=="SELL"}
    need(not buys.intersection(sells),"OPPOSITE_FILL_TIME_ORDER_AMBIGUOUS")
    quantity=0;cost=Fraction(0);realized=Fraction(0);buy_quantity=sell_quantity=0
    for at,fill,price in sorted(timeline,key=lambda item:item[0]):
        q=fill["quantity"]
        if fill["side"]=="BUY":
            quantity+=q;buy_quantity+=q;cost+=price*q
        else:
            need(q<=quantity,"EXIT_PRECEDES_AVAILABLE_ENTRY_FILLS")
            average=cost/quantity
            realized+=(price-average)*q
            cost-=average*q;quantity-=q;sell_quantity+=q
    need(quantity==value["remaining_quantity"],"SIGNED_REMAINING_QUANTITY_MISMATCH")
    terminal=all(o["status"] in {"FILLED","CANCELLED","REJECTED"} for o in orders.values())
    need(value["all_referenced_orders_terminal"] is terminal
         and value["fixture_flat_reference_verified"] is (quantity==0 and terminal),
         "FLAT_REFERENCE_INCONSISTENT")
    gross=exact_paise(realized);basis=exact_paise(cost)
    aggregate=None
    if fee_capture is not None:
        fee=authenticated(fee_capture,pin)
        need(fee.get("model")=="HILEGA_AGGREGATE_FEE_REPORT_CAPTURE_V1"
             and fee.get("profile_verified_before_and_after") is True,
             "PINNED_AGGREGATE_FEE_CAPTURE_REQUIRED")
        start,end=aware(fee["started_at"]),aware(fee["completed_at"])
        need(start<=end<=now and (end-start).total_seconds()<=30
             and (now-start).total_seconds()<=30 and day(start)==day(end)==day(now)
             and fee["session_date"]==day(now) and fee["query"]==query(day(now)),
             "FEE_CAPTURE_STALE_FUTURE_OR_WRONG_SCOPE")
        need(all(fee.get(k) is False for k in (
            "source_atomic","orders_sent","production_execution_enabled","entry_permission")),
            "FEE_CAPTURE_AUTHORITY_FORBIDDEN")
        aggregate=assess_response(fee["provider_response"])["reported_aggregate_total_paise"]
    reasons=["FIXTURE_ONLY_NO_LIVE_OWNERSHIP_AUTHORITY",
             "STRATEGY_FEE_ALLOCATION_UNVERIFIED",
             "PRODUCTION_ACCOUNTING_POLICY_UNAPPROVED",
             "PRODUCTION_DAILY_STOP_NOT_INTEGRATED"]
    if fee_capture is None:reasons.append("AGGREGATE_FEE_CAPTURE_NOT_SUPPLIED")
    if quantity:reasons.append("OPEN_POSITION_MARK_NOT_AUTHENTICATED")
    if gross["integer_paise"] is None:reasons.append("GROSS_PAISE_ROUNDING_POLICY_REQUIRED")
    return dict(model="HILEGA_GROSS_PNL_FIXTURE_PREVIEW_V1",
        status="GROSS_PREVIEW_NET_PNL_AND_RISK_BLOCKED",
        calculation_policy="FIXTURE_MOVING_AVERAGE_GROSS_V1",
        assessed_at=as_of,buy_filled_quantity=buy_quantity,
        sell_filled_quantity=sell_quantity,remaining_quantity=quantity,
        gross_realized_paise=gross["integer_paise"],
        gross_realized_paise_fraction=dict(numerator=gross["numerator"],denominator=gross["denominator"]),
        remaining_cost_basis_paise_fraction=dict(numerator=basis["numerator"],denominator=basis["denominator"]),
        open_gross_pnl_paise=0 if value["fixture_flat_reference_verified"] else None,
        reported_account_aggregate_fee_paise=aggregate,
        aggregate_fee_capture_assessed=fee_capture is not None,
        account_aggregate_fees_applied_to_strategy=False,
        strategy_fees_paise=None,fees_complete=False,
        realized_net_pnl_paise=None,open_net_pnl_paise=None,
        reasons=sorted(reasons),live_pnl_authenticated=False,
        runtime_integration=False,risk_gate_input_ready=False,
        entry_permission=False,reservation_release_permission=False,
        orders_sent=False,production_execution_enabled=False,production_ready=False)

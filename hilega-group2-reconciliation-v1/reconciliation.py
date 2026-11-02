"""Pure candidate reconciliation. No broker transport, database writes, or execution authority."""
from decimal import Decimal


def need(ok,reason):
    if not ok:raise ValueError(reason)


def cents(value):
    need(type(value) is int and value>=0,'NONNEGATIVE_INTEGER_CENTS_REQUIRED');return value


def reservation(held_cents,order_state,requested,filled,*,position_flat,broker_reconciled,fees_final):
    cents(held_cents)
    need(type(requested) is int and type(filled) is int and requested>0 and 0<=filled<=requested,'INVALID_QUANTITIES')
    need(order_state in {'UNKNOWN','WORKING','PARTIAL','FILLED','CANCELLED','REJECTED'},'INVALID_ORDER_STATE')
    need(all(type(x) is bool for x in (position_flat,broker_reconciled,fees_final)),'EXPLICIT_RECONCILIATION_FLAGS_REQUIRED')
    need(order_state!='FILLED' or filled==requested,'FILLED_QUANTITY_MISMATCH')
    terminal=order_state in {'FILLED','CANCELLED','REJECTED'}
    eligible=terminal and position_flat and broker_reconciled and fees_final
    return dict(candidate_local_release_cents=held_cents if eligible else 0,
        remaining_local_hold_cents=0 if eligible else held_cents,
        broker_cash_addback_cents=0,release_executed=False,production_permission=False,
        automatic_resubmission=False,requires_signed_current_context=True)


def fee_attribution(trades,charges,*,coverage_complete):
    need(type(coverage_complete) is bool,'EXPLICIT_CHARGE_COVERAGE_REQUIRED')
    ids=set();by_cycle={};gross={}
    for t in trades:
        need(isinstance(t['trade_id'],str) and t['trade_id'] and t['trade_id'] not in ids,'DUPLICATE_OR_INVALID_TRADE_ID');ids.add(t['trade_id'])
        need(isinstance(t['cycle_id'],str) and bool(t['cycle_id']),'CYCLE_ID_REQUIRED')
        need(t['side'] in {'BUY','SELL'},'INVALID_TRADE_SIDE')
        amount=cents(t['value_cents']);cycle=t['cycle_id'];by_cycle.setdefault(cycle,0)
        gross[cycle]=gross.get(cycle,0)+(amount if t['side']=='SELL' else -amount)
    seen=set();attributed=set()
    for c in charges:
        need(c['trade_id'] in ids,'UNMATCHED_BROKER_CHARGE')
        key=(c['trade_id'],c['component']);need(isinstance(c['component'],str) and bool(c['component']) and key not in seen,'DUPLICATE_OR_INVALID_CHARGE_COMPONENT');seen.add(key)
        t=next(t for t in trades if t['trade_id']==c['trade_id']);by_cycle[t['cycle_id']]+=cents(c['amount_cents']);attributed.add(c['trade_id'])
    complete=coverage_complete and bool(ids) and attributed==ids
    return dict(attribution_complete=complete,cycles={k:dict(gross_cashflow_cents=gross[k],charges_cents=v,
        net_cashflow_cents=gross[k]-v if complete else None) for k,v in by_cycle.items()},
        net_pnl_certified=False,positions_and_cost_basis_still_required=True,actual_broker_fees_collected=False)


def enrollment_preflight(active_preparations,owner_exists,*,controller_paused):
    need(type(active_preparations) is int and active_preparations>=0 and type(owner_exists) is bool and type(controller_paused) is bool,'INVALID_PREFLIGHT')
    reasons=[]
    if active_preparations!=1:reasons.append('ONE_FRESH_DISABLED_PREPARATION_REQUIRED')
    if owner_exists:reasons.append('EXISTING_OWNER_REQUIRES_REVIEW')
    if not controller_paused:reasons.append('PAUSED_CONTROLLER_REQUIRED')
    return dict(blockers=reasons,structural_preconditions_present=not reasons,
        freshness_verified=False,signed_ownership_verified=False,trusted_authority_provisioned=False,
        live_enrollment_permitted=False,production_execution_enabled=False)

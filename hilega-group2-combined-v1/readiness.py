"""Read-only Group 2 evidence and conservative candidate assessments. No execution authority."""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN


class Blocked(ValueError):pass


def need(ok,reason):
    if not ok:raise Blocked(reason)


def money(value):
    need(not isinstance(value,bool) and isinstance(value,(str,int,float,Decimal)),'INVALID_CASH_OR_CHARGE')
    amount=Decimal(str(value));need(amount.is_finite() and amount>=0,'INVALID_CASH_OR_CHARGE');return amount


def profile_capabilities(raw):
    data=raw.get('data',{}) if isinstance(raw,dict) else {}
    need(isinstance(raw,dict) and raw.get('status')=='success' and isinstance(data,dict),'PROFILE_RESPONSE_INVALID')
    checks=dict(active=data.get('is_active') is True,nfo_enabled='NFO' in data.get('exchanges',[]),
        intraday_enabled='I' in data.get('products',[]),limit_orders_enabled='LIMIT' in data.get('order_types',[]))
    return dict(checks=checks,capabilities_present=all(checks.values()),execution_permission=False)


def cash_preview(cash,held_cents):
    need(type(held_cents) is int and held_cents>=0,'INVALID_LOCAL_HOLD')
    cents=int((money(cash)*100).to_integral_value(rounding=ROUND_DOWN));cap=cents//2
    return dict(observed_cash_cents=cents,half_cash_cap_cents=cap,local_hold_cents=held_cents,
        conservative_capacity_cents=max(0,cap-held_cents),broker_cash_added_back_cents=0,
        allocation_policy_approved=False,reservation_release_permission=False,entry_permission=False)


def order_state_policy(status,quantity,filled):
    need(type(quantity) is int and type(filled) is int and 0<=filled<=quantity and quantity>0,'INVALID_ORDER_QUANTITIES')
    need(status in {'UNKNOWN','WORKING','PARTIAL','FILLED','CANCELLED','REJECTED'},'UNKNOWN_ORDER_STATE')
    action='BLOCK_UNKNOWN_NO_RESUBMISSION' if status=='UNKNOWN' else 'OBSERVE_WITHOUT_RESUBMISSION'
    if status in {'CANCELLED','REJECTED'}:action='MANUAL_RESIDUAL_REVIEW_REQUIRED' if filled<quantity else 'FILLED_QUANTITY_RECONCILIATION_REQUIRED'
    if status=='FILLED':
        need(filled==quantity,'FILLED_STATUS_QUANTITY_MISMATCH');action='SIGNED_POSITION_RECONCILIATION_REQUIRED'
    return dict(action=action,remaining_quantity=quantity-filled,automatic_resubmission=False,
        cancel_or_reprice_permission=False,production_policy_approved=False)


def reconcile_charge_totals(total,components):
    need(isinstance(components,dict) and bool(components),'CHARGE_COMPONENTS_REQUIRED')
    expected=sum((money(v) for v in components.values()),Decimal(0));observed=money(total)
    need(abs(expected-observed)<=Decimal('0.01'),'CHARGE_TOTAL_COMPONENT_MISMATCH')
    return dict(aggregate_total_verified=True,per_cycle_attribution_verified=False,
        actual_broker_charges_collected=False,fees_complete=False)


def collect(client,pin,api,observation,*,clock=lambda:datetime.now(timezone.utc)):
    start=clock();first=client.get('profile');api.matches(first,pin);capabilities=profile_capabilities(first)
    cash_before=observation.sanitize(client.get('funds'),'funds');need(cash_before['status']=='PASS','FUNDS_BEFORE_UNAVAILABLE')
    account=api.capture(client,pin,clock=clock)
    need(account.get('status')=='READ_ONLY_CAPTURED','SIGNED_ACCOUNT_CAPTURE_BLOCKED')
    cash_after=observation.sanitize(client.get('funds'),'funds');need(cash_after['status']=='PASS','FUNDS_AFTER_UNAVAILABLE')
    api.matches(client.get('profile'),pin);end=clock()
    need(start.tzinfo is not None and end.tzinfo is not None and 0<=(end-start).total_seconds()<=30
        and api.day(start)==api.day(end),'GROUP2_CAPTURE_SLOW_OR_SESSION_CHANGED')
    api.verify(account,pin,as_of=end.isoformat())
    evidence=dict(model='HILEGA_GROUP2_READ_ONLY_ACCOUNT_CASH_EVIDENCE_V1',assessed_at=end.isoformat(),
        account_scope=pin['scope'],account_capture=account,funds_before=cash_before,funds_after=cash_after,
        capabilities=capabilities,production_execution_enabled=False,entry_permission=False,orders_sent=False,
        reservation_release_permission=False)
    evidence['signature']=api.sign(evidence,pin)
    issues=account.get('diagnostics',{}).get('issues',[])
    summary=dict(status='BROKER_GET_ACCOUNT_CASH_CAPTURE_PASS',assessed_at=end.isoformat(),
        account_identity_verified=True,signed_account_capture_verified=True,cash_schema_verified=True,
        funds_changed_during_capture=cash_before!=cash_after,capabilities=capabilities,
        order_count=len(account['orders']),trade_count=len(account['trades']),position_row_count=len(account['positions']),
        nonzero_position_count=sum(p['quantity']!=0 for p in account['positions']),diagnostic_issue_count=len(issues),
        account_position_rows_complete=account.get('account_position_rows_complete') is True,
        broker_token_read_only_scopes_verified=False,broker_network_get_validated=True,
        strategy_ownership_verified=False,fees_complete=False,broker_cash_release_implemented=False,
        production_execution_enabled=False,production_ready=False)
    return evidence,summary


def milestone(broker_summary=None):
    captured=bool(broker_summary and broker_summary.get('broker_network_get_validated'))
    return dict(group1='CLOSED_WORKER_DEPLOYMENT_VERIFIED',group2_complete=False,
        tasks=[dict(task='BROKER_ACCOUNT_AND_CASH_READS',status='CAPTURED_REVIEW_REQUIRED' if captured else 'AWAITING_EXPLICIT_BROKER_READ'),
            dict(task='TRUSTED_PRODUCTION_AUTHORITY',status='NOT_PROVISIONED'),
            dict(task='EXECUTION_FACTORY_AND_OWNER_INTEGRATION',status='NOT_CONFIGURED'),
            dict(task='ORDER_LIMIT_PARTIAL_AND_UNKNOWN_POLICIES',status='CONSERVATIVE_CANDIDATE_REQUIRES_APPROVAL'),
            dict(task='FEES_AND_NET_PNL',status='AGGREGATE_VALIDATOR_ONLY_NOT_RECONCILED'),
            dict(task='CASH_RESERVATION_AND_RELEASE',status='READ_ONLY_PREVIEW_ONLY')],
        group3='PENDING_CONTROLLED_LIVE_RELEASE',production_execution_enabled=False,production_ready=False)

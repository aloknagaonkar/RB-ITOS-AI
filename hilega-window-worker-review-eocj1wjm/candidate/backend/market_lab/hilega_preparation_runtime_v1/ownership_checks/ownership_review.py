"""Read-only single filled BUY-entry reconciliation. Never an exit permission."""
from decimal import Decimal, ROUND_DOWN
import hmac
import json
import re
from .bridge import correlate
from .historical_receipt_checks import sha
from .reservation_checks import POLICY, verify_row
from .risk_evidence_audit import FLAGS, need
from .signature_checks import aware, day, sign


def authenticate_historical_cash(bundle, pin):
    cash=bundle.get('cash_capture')
    need(isinstance(cash,dict),'NESTED_CASH_CAPTURE_REQUIRED')
    payload=dict(cash);signature=payload.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(payload,pin),signature),
         'NESTED_CASH_SIGNATURE_INVALID')
    need(cash.get('model')=='HILEGA_READ_ONLY_CASH_OBSERVATION_V1'
         and cash.get('evidence_mode')=='LIVE_READ_ONLY_ACCOUNT_PINNED'
         and cash.get('account_scope')==pin['scope']
         and cash.get('account_identity_verified') is True
         and cash.get('account_position_rows_complete') is True
         and cash.get('status')=='READ_ONLY_CAPTURED','NESTED_CASH_IDENTITY_INVALID')
    need(all(cash.get(k) is False for k in ('orders_sent','entry_permission',
         'production_execution_enabled')),'NESTED_CASH_PERMISSION_INVALID')
    start,end=aware(cash['started_at']),aware(cash['completed_at'])
    need(aware(bundle['started_at'])<=start<=end<=aware(bundle['completed_at'])
         and (end-start).total_seconds()<=30
         and day(start)==day(end)==cash.get('session_date')==bundle['session_date'],
         'NESTED_CASH_HISTORICAL_WINDOW_INVALID')
    before,after=cash.get('funds_before'),cash.get('funds_after')
    need(isinstance(before,dict) and before==after==bundle.get('cash_before_market')
         ==bundle.get('cash_after_market')
         and cash.get('funds_changed_during_capture') is False,
         'HISTORICAL_CASH_CHANGED')
    need(after.get('field')=='data.available_to_trade.cash_available_to_trade.total',
         'HISTORICAL_NET_CASH_FIELD_REQUIRED')
    raw=after.get('cash_available_to_trade')
    need(type(raw) in (str,int,float),'HISTORICAL_CASH_AMOUNT_INVALID')
    value=Decimal(str(raw))
    need(value.is_finite() and value>=0,'HISTORICAL_CASH_AMOUNT_INVALID')
    need(all(isinstance(cash.get(k),list) for k in ('orders','trades','positions')),
         'HISTORICAL_ACCOUNT_ROWS_REQUIRED')
    need(not cash['orders'] and not cash['trades']
         and all(type(p.get('quantity')) is int and p['quantity']==0
                 for p in cash['positions']), 'HISTORICAL_BASELINE_NOT_EMPTY')
    need(cash.get('diagnostics',{}).get('issues')==[],
         'HISTORICAL_CASH_DIAGNOSTICS_REQUIRE_REVIEW')
    return int((value*100).to_integral_value(rounding=ROUND_DOWN))//2


def reconcile_entry(source,snapshot,pin,*,as_of,mode='LIVE_CLOSED',verifier=None):
    need(mode in {'LIVE_CLOSED','OFFLINE_FIXTURE'} and source['mode']==mode,
         'OWNERSHIP_EVIDENCE_MODE_MISMATCH')
    if mode=='LIVE_CLOSED':
        need(re.fullmatch(r'UPSTOX:[0-9a-f]{64}',pin['scope']) is not None,
             'LIVE_UPSTOX_PIN_SCOPE_REQUIRED')
    else:need(pin['scope'].startswith('FIXTURE:'),'EXPLICIT_FIXTURE_SCOPE_REQUIRED')
    need(source['control'].get('production_execution_enabled') is False
         and source['control'].get('mode')=='PAUSED',
         'CLOSED_CONTROLLER_REQUIRED')
    stop=source.get('stop_state')
    need(isinstance(stop,list) and len(stop)==2
         and all(type(v) is int and v>=0 for v in stop) and stop[0]==stop[1],
         'UNHANDLED_OR_UNKNOWN_STOP_STATE')
    kwargs={} if verifier is None else dict(verifier=verifier)
    bridge=correlate(source,snapshot,pin,as_of=as_of,**kwargs)
    reasons=[]
    if not source['bindings']:reasons.append('NO_BOUND_APPLICATION_ENTRY')
    if len(source['bindings'])>1:reasons.append('MULTIPLE_ENTRY_LIFECYCLE_NOT_SUPPORTED')
    if not bridge['historical_ack_reference_count']:reasons.append('NO_DURABLE_ENTRY_ACK')
    position=bridge['position_reference_review']
    reasons.extend(position['position_reference_reasons'])
    if any(source['counts'][k] for k in ('intents','sim_orders','sim_fills','sim_allocation_reservations')):
        reasons.append('SIMULATOR_ACTIVITY_CANNOT_ESTABLISH_LIVE_OWNERSHIP')
    if set(source['bindings'])!=set(source['plans']):reasons.append('UNBOUND_APPLICATION_PREPARATION')
    if set(source['bindings'])!={r[0] for r in source['requests']}:
        reasons.append('UNBOUND_ADAPTER_REQUEST')
    if set(source.get('cash_reservations',{}))!=set(source['bindings']):
        reasons.append('LOCAL_RESERVATION_BINDING_SET_MISMATCH')
    if len(source['attempts'])!=len(source['bindings']) or any(r[2]!='PLACE' for r in source['attempts']):
        reasons.append('ADDITIONAL_OR_MISSING_TRANSPORT_ATTEMPT')
    if len(source['receipts'])!=len(source['bindings']):reasons.append('EXACT_ENTRY_RECEIPT_REQUIRED')
    if any(o['side']!='BUY' for o in snapshot['orders']):reasons.append('SELL_LIFECYCLE_NOT_SUPPORTED')
    if any(o['status']!='FILLED' for o in snapshot['orders']):reasons.append('FULLY_FILLED_ENTRY_REQUIRED')
    if not snapshot['trades']:reasons.append('NO_ACTUAL_ENTRY_FILLS')
    if source['bindings'] and source.get('cash_policy')!=dict(
        scope=pin['scope'],mode='APPLICATION_LOCAL_REFERENCE_ONLY',policy=POLICY):
        reasons.append('LOCAL_CASH_POLICY_NOT_BOUND')
    authenticated=0
    for key,binding in source['bindings'].items():
        reservation=source.get('cash_reservations',{}).get(key)
        if reservation is None:continue
        verify_row(reservation,pin)
        need(reservation['state']=='RESERVED_DISABLED_REQUEST','UNKNOWN_OUTCOME_HOLD_RETAINED')
        plan,hold,out=(source[n][key] for n in ('plans','holds','outbox'))
        need(reservation['id']==key and reservation['request_fingerprint']==binding['request_fingerprint']
             and reservation['plan_fingerprint']==sha(plan)
             and reservation['shadow_hold_fingerprint']==sha(hold)
             and reservation['outbox_fingerprint']==sha(out), 'SIGNED_RESERVATION_BINDING_MISMATCH')
        need(reservation.get('local_reference_reserved') is True
             and reservation['amount_cents']==binding['held_cents']==hold['held_cents']
             and reservation['cash_cap_cents']==binding['cash_cap_cents'],
             'SIGNED_RESERVATION_AMOUNT_MISMATCH')
        request=next(json.loads(raw) for rid,fp,raw in source['requests'] if rid==key)
        if request.get('state')!='ACKNOWLEDGED_NOT_FILLED':
            reasons.append('ADAPTER_OUTCOME_NOT_ACKNOWLEDGED')
        signal=aware(request['signal_at']);created=aware(reservation['created_at'])
        need(day(signal)==reservation['session_date']==snapshot['session_date']
             and signal<=created<=aware(snapshot['generated_at'])
             and plan.get('signal_at')==request['signal_at']
             and plan.get('direction')==request['direction'], 'ENTRY_SESSION_OR_SIGNAL_LINK_INVALID')
        bundle=json.loads(source['evidence'][binding['bundle_fingerprint']])
        need(bundle['session_date']==snapshot['session_date'],'HISTORICAL_BUNDLE_SESSION_MISMATCH')
        cap=authenticate_historical_cash(bundle,pin)
        need(cap==binding['cash_cap_cents'],'HISTORICAL_HALF_CASH_CAP_MISMATCH')
        need(reservation['fee_buffer_approved_for_production'] is False,
             'UNEXPECTED_FEE_APPROVAL_CLAIM')
        need(all(type(reservation[k]) is int and reservation[k]>0
                 for k in ('premium_cents','fee_buffer_cents'))
             and reservation['premium_cents']+reservation['fee_buffer_cents']<=reservation['amount_cents'],
             'RESERVATION_PREMIUM_BUFFER_INVALID')
        authenticated+=1
    reasons=sorted(set(reasons))
    passed=not reasons and authenticated==1
    live=mode=='LIVE_CLOSED'
    quantity=bridge['current_bound_fill_quantity'] if passed else None
    return dict(model='HILEGA_CURRENT_ENTRY_OWNERSHIP_REVIEW_V1',
        status=('CURRENT_ENTRY_QUANTITY_RECONCILED_READ_ONLY' if live else
                'FIXTURE_ENTRY_QUANTITY_RECONCILED') if passed else 'BLOCKED_ENTRY_OWNERSHIP_GAPS',
        scope='SINGLE_CURRENT_FULLY_FILLED_BUY_ENTRY_ONLY',assessed_at=as_of,
        reasons=reasons,current_entry_ownership_verified=passed and live,
        fixture_entry_quantity_reconciled=passed and not live,
        reviewed_remaining_entry_quantity=quantity,
        authenticated_reservation_count=authenticated,
        historical_nested_cash_authenticated=authenticated>0,
        historical_cash_is_current_entry_evidence=False,
        current_account_signature_and_identity_verified=True,
        account_capture_generated_at=snapshot['generated_at'],
        account_capture_completed_at=snapshot['completed_at'],
        account_capture_age_seconds=bridge['account_capture_age_seconds'],
        evidence_sources_atomic=False,ownership_ledger_persisted=False,
        lifecycle_ownership_integrated=False,order_modification_history_assessed=False,
        current_contract_and_quote_pricing_revalidated=False,
        strategy_ownership_verified=False,exit_submission_permission=False,
        reservation_release_permission=False,real_funds_reservation_verified=False,
        fees_complete=False,realized_net_pnl_paise=None,open_net_pnl_paise=None,
        risk_gate_input_ready=False,entry_permission=False,orders_sent=False,
        production_execution_enabled=False,production_ready=False,
        live_evidence_assessed=live,database_modified=False,controller_changed=False,
        entry_allocation_fraction='0.50',daily_loss_limit_required=False)

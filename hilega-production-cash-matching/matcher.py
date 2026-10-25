"""Offline evidence-contract model. No live debit inference or trading permission."""
from datetime import datetime
from decimal import Decimal,ROUND_DOWN,ROUND_UP,InvalidOperation
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
class Blocked(ValueError):pass

def amount(v):
    if isinstance(v,bool) or not isinstance(v,(str,int,float,Decimal)):raise Blocked('INVALID_AMOUNT')
    try:d=Decimal(str(v))
    except InvalidOperation:raise Blocked('INVALID_AMOUNT') from None
    if not d.is_finite() or d<0:raise Blocked('INVALID_AMOUNT')
    return d

def quant(v,up=False):return amount(v).quantize(Decimal('.01'),rounding=ROUND_UP if up else ROUND_DOWN)
def at(v):
    try:t=datetime.fromisoformat(v)
    except (ValueError,TypeError):raise Blocked('INVALID_TIMESTAMP') from None
    if t.tzinfo is None:raise Blocked('AWARE_TIME_REQUIRED')
    return t.astimezone(IST)
def identity(v):
    if not isinstance(v,str) or not 1<=len(v)<=200 or any(ord(c)<32 for c in v):raise Blocked('INVALID_IDENTITY')
    return v

def evaluate(snapshot,reservations,proofs,*,as_of):
    """Proofs are explicit synthetic fixture assertions, NOT Upstox API fields.
    reported cash alone never establishes order-level reflected premium.
    """
    now=at(as_of)
    if snapshot.get('evidence_mode')!='OFFLINE_FIXTURE':raise Blocked('OFFLINE_FIXTURES_ONLY')
    scope=identity(snapshot.get('account_scope'));sid=identity(snapshot.get('snapshot_id'))
    observed=at(snapshot.get('observed_at'))
    if snapshot.get('complete') is not True or not 0<=(now-observed).total_seconds()<=30 or observed.date()!=now.date():raise Blocked('STALE_INCOMPLETE_OR_WRONG_SESSION')
    cash=amount(snapshot.get('available_cash'));cap=quant(cash*Decimal('.5'))
    if not isinstance(reservations,list) or not isinstance(proofs,list):raise Blocked('LISTS_REQUIRED')
    if snapshot.get('coherent') is not True:raise Blocked('NONCOHERENT_EVIDENCE_CANNOT_MATCH_DEBITS')
    orders=snapshot.get('orders');positions=snapshot.get('positions')
    if not isinstance(orders,list) or not isinstance(positions,list):raise Blocked('ORDER_POSITION_EVIDENCE_REQUIRED')
    ordermap={};known=set();seenproof=set();proofmap={};result=[];issues=[];ownedorders=set()
    for o in orders:
        oid=identity(o.get('order_id'))
        if oid in ordermap:raise Blocked('DUPLICATE_BROKER_ORDER')
        ordermap[oid]=o
    for proof in proofs:
        rid=identity(proof.get('reservation_id'))
        if rid in proofmap:raise Blocked('DUPLICATE_RESERVATION_PROOF')
        proofmap[rid]=proof
    for row in reservations:
        rid=identity(row.get('reservation_id'))
        if rid in known:raise Blocked('DUPLICATE_RESERVATION')
        known.add(rid)
        if row.get('account_scope')!=scope:raise Blocked('RESERVATION_ACCOUNT_MISMATCH')
        reserved=quant(row.get('reserved_amount'),up=True);oid=row.get('order_id')
        state=row.get('state')
        if state not in {'RESERVED','SUBMITTED','PARTIAL','FILLED','UNKNOWN','CANCEL_PENDING','EXIT_PENDING','TERMINAL_FLAT'}:raise Blocked('RESERVATION_STATE_INVALID')
        reasons=[];reflected=Decimal(0);released=Decimal(0);proof=proofmap.get(rid)
        if state=='UNKNOWN':reasons.append('ORDER_ACCEPTANCE_UNKNOWN')
        order=ordermap.get(oid) if oid else None
        if oid:
            identity(oid)
            if oid in ownedorders:raise Blocked('ORDER_SHARED_BY_MULTIPLE_RESERVATIONS')
            ownedorders.add(oid)
        if state!='RESERVED' and order is None:reasons.append('BOUND_ORDER_NOT_IN_COMPLETE_SNAPSHOT')
        if order is not None:
            if order.get('instrument')!=row.get('instrument') or order.get('product')!=row.get('product') or order.get('side')!='BUY':reasons.append('ORDER_IDENTITY_MISMATCH')
            for k in ('quantity','filled','pending'):
                if type(order.get(k))is not int or order[k]<0:raise Blocked('ORDER_QUANTITY_INVALID')
            if order['filled']+order['pending']>order['quantity']:raise Blocked('ORDER_QUANTITIES_INCONSISTENT')
            if order['quantity']!=row.get('quantity'):reasons.append('ORDER_QUANTITY_MISMATCH')
            if order.get('status') not in {'OPEN','PARTIAL','FILLED','CANCELLED','REJECTED','UNKNOWN'}:raise Blocked('ORDER_STATUS_INVALID')
            if order['status']=='UNKNOWN':reasons.append('BROKER_ORDER_STATUS_UNKNOWN')
            if order['status']=='FILLED' and (order['filled']!=order['quantity'] or order['pending']):raise Blocked('INCONSISTENT_FILLED_ORDER')
            if order['status'] in {'CANCELLED','REJECTED'} and order['pending']:raise Blocked('TERMINAL_ORDER_HAS_PENDING_QUANTITY')
        if proof:
            seenproof.add(rid)
            if (proof.get('account_scope')!=scope or proof.get('snapshot_id')!=sid or proof.get('order_id')!=oid
                or proof.get('kind')!='EXPLICIT_OFFLINE_ATTRIBUTION_ASSERTION'):
                reasons.append('ATTRIBUTION_PROOF_SCOPE_OR_SNAPSHOT_MISMATCH')
            else:
                overlap=quant(proof.get('reflected_amount'))
                if overlap>reserved:reasons.append('REFLECTED_AMOUNT_EXCEEDS_RESERVATION')
                elif not reasons and order is not None:reflected=overlap
        elif state not in {'RESERVED'}:reasons.append('NO_EXPLICIT_REFLECTION_PROOF')
        # Evidence of complete basket/position closure is distinct from a cancelled
        # entry: cancelled orders can still have filled exposure.
        if state=='TERMINAL_FLAT':
            matching=[p for p in positions if p.get('instrument')==row.get('instrument') and p.get('product')==row.get('product')]
            if len(matching)!=1 or type(matching[0].get('quantity'))is not int or matching[0]['quantity']!=0:
                reasons.append('FLAT_POSITION_NOT_VERIFIED')
            if proof is None or proof.get('all_related_orders_terminal') is not True or proof.get('all_exit_fills_verified') is not True:
                reasons.append('TERMINAL_EXIT_FILL_PROOF_REQUIRED')
            if order is None or order.get('status') not in {'FILLED','CANCELLED','REJECTED'}:reasons.append('ENTRY_NOT_TERMINAL')
            if not reasons:released=reserved;reflected=Decimal(0)
        if reasons:
            reflected=Decimal(0);released=Decimal(0)
        hold=reserved-released;unreflected=max(Decimal(0),hold-reflected)
        result.append(dict(reservation_id=rid,state=state,reserved_amount=str(reserved),local_hold=str(hold),
            reflected_in_broker_cash=str(reflected),unreflected_local_hold=str(unreflected),release_amount=str(released),
            review_required=bool(reasons),reasons=sorted(set(reasons))))
    if set(proofmap)-known:raise Blocked('PROOF_WITHOUT_RESERVATION')
    # Any unowned order or position makes account-level cash attribution ambiguous.
    if set(ordermap)-ownedorders:issues.append('UNMAPPED_ACCOUNT_ORDER_ACTIVITY')
    mapped_instruments={(x.get('instrument'),x.get('product')) for x in reservations}
    for p in positions:
        if type(p.get('quantity'))is not int:raise Blocked('POSITION_QUANTITY_INVALID')
        if p['quantity'] and (p.get('instrument'),p.get('product')) not in mapped_instruments:issues.append('UNMAPPED_ACCOUNT_POSITION')
    if snapshot.get('unrelated_cash_activity') is not False:issues.append('CASH_ACTIVITY_CONFOUNDED_OR_UNKNOWN')
    if issues:
        for r in result:
            r.update(reflected_in_broker_cash='0.00',release_amount='0.00',local_hold=r['reserved_amount'],unreflected_local_hold=r['reserved_amount'],review_required=True)
            r['reasons']=sorted(set(r['reasons']+issues))
    holds=sum((Decimal(r['local_hold']) for r in result),Decimal(0));unreflected=sum((Decimal(r['unreflected_local_hold']) for r in result),Decimal(0))
    reflected=sum((Decimal(r['reflected_in_broker_cash']) for r in result),Decimal(0))
    review=bool(issues or any(r['review_required'] for r in result))
    return dict(model='HILEGA_OFFLINE_CASH_MATCHING_V1',status='REVIEW_REQUIRED' if review else 'MATCHED_OFFLINE_FIXTURE',
        available_broker_cash=str(cash),half_current_cash_cap=str(cap),full_local_holds=str(holds),
        explicitly_reflected_overlap=str(reflected),unreflected_hold_deduction=str(unreflected),
        capacity_preview=str(max(Decimal(0),cap-unreflected)),reservations=result,issues=sorted(set(issues)),
        new_entry_eligibility_blocked=review,entry_permission=False,production_execution_enabled=False,
        orders_sent=False,real_debit_attribution='NOT_VALIDATED',broker_cash_addback='0.00',evidence_mode='OFFLINE_FIXTURE')

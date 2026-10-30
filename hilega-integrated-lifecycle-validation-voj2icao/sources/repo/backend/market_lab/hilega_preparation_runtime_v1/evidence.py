"""Signed account/market evidence -> unsent preparation preview. No authority."""
import hashlib
import hmac
import importlib.util
import json
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from zoneinfo import ZoneInfo
from market_lab.hilega_production_account_adapter_v1 import canonical,sign,aware,day

ROOT = Path(__file__).resolve().parents[3]
MODEL = 'HILEGA_SIGNED_PREPARATION_EVIDENCE_V1'
MODE = 'LIVE_READ_ONLY_ACCOUNT_PINNED'
FLAGS = dict(orders_sent=False,production_execution_enabled=False,entry_permission=False,
    application_ledger_updated=False,strategy_ownership_verified=False,
    real_funds_reservation_verified=False,reservation_release_permission=False,
    allocation_reserved=False,source_atomic=False)


class Blocked(ValueError):pass


def need(value,reason):
    if not value:raise Blocked(reason)


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def load(path,name,aliases=None):
    aliases=aliases or {}
    saved={k:sys.modules.get(k) for k in aliases}
    try:
        sys.modules.update(aliases)
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for k,v in saved.items():
            if v is None:sys.modules.pop(k,None)
            else:sys.modules[k]=v


def dependencies(root=ROOT):
    manifest=json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for relative,fingerprint in manifest.items():
        p=root/relative
        need(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==fingerprint,
             'INSTALLED_DEPENDENCY_VERSION_MISMATCH')
    rules=load(root/'hilega-production-contract-preview/rules.py','preflight_contract_rules')
    gate=load(root/'hilega-production-real-cash-shadow-gate/gate.py','preflight_cash_gate')
    return rules,gate


def fresh_window(start,end,as_of):
    start,end,now=map(aware,(start,end,as_of))
    need(start<=end<=now and (end-start).total_seconds()<=30 and
         (now-start).total_seconds()<=30 and day(start)==day(end)==day(now),
         'BUNDLE_STALE_FUTURE_SLOW_OR_WRONG_SESSION')
    return now


def validate(bundle,pin,*,as_of):
    rules,gate=dependencies()
    value=dict(bundle);signature=value.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(value,pin),signature),
         'BUNDLE_SIGNATURE_INVALID')
    need(value.get('model')==MODEL and value.get('evidence_mode')==MODE,
         'LIVE_SIGNED_BUNDLE_REQUIRED')
    need(value.get('account_scope')==pin['scope'],'BUNDLE_ACCOUNT_SCOPE_MISMATCH')
    need(all(value.get(k) is False for k in FLAGS),'READ_ONLY_FLAGS_REQUIRED')
    now=fresh_window(value['started_at'],value['completed_at'],as_of)
    need(value['session_date']==day(now),'BUNDLE_SESSION_MISMATCH')
    need(value.get('profile_verified_before_and_after') is True,'ACCOUNT_IDENTITY_UNVERIFIED')
    cash=value['cash_capture']
    need(aware(value['started_at'])<=aware(cash['started_at'])<=aware(cash['completed_at'])<=aware(value['completed_at']),
         'CASH_OUTSIDE_BUNDLE_WINDOW')
    cash_evidence=gate.verify_capture(cash,pin,as_of=as_of)
    need(value.get('cash_before_market')==cash['funds_before']==cash['funds_after']==value.get('cash_after_market'),
         'FUNDS_CHANGED_DURING_BUNDLE')
    need(value.get('market_before',{}).get('exchange')=='NSE' and
         value.get('market_after',{}).get('exchange')=='NSE','MARKET_EXCHANGE_INVALID')
    market_ok=(value['market_before'].get('status')==value['market_after'].get('status')=='NORMAL_OPEN')
    spot=value['spot_initial']
    mapping=rules.select(value['contracts'],spot,[0],1,now.astimezone(rules.IST).date())
    keys=[rules.UNDERLYING]+[r['instrument_key'] for r in mapping['contracts']]
    quotes=rules.quote_map(value['quotes'],keys)
    refreshed=rules.select(value['contracts'],quotes[rules.UNDERLYING]['last_price'],[0],1,
                           now.astimezone(rules.IST).date())
    need(refreshed['atm']==mapping['atm'],'ATM_CHANGED_DURING_BUNDLE')
    for row in mapping['contracts']:
        need(re.fullmatch(r'NSE_FO\|[0-9]+',row['instrument_key']) is not None,
             'EXACT_BROKER_CONTRACT_KEY_REQUIRED')
    underlying=quotes[rules.UNDERLYING]
    age=(now-rules.timestamp(underlying['timestamp'])).total_seconds()
    global_reasons=list(cash_evidence['reasons'])
    if not market_ok:global_reasons.append('MARKET_NOT_NORMAL_OPEN')
    if not 0<=age<=10:global_reasons.append('UNDERLYING_QUOTE_STALE_OR_FUTURE')
    if cash_evidence['half_cash_cap_cents']==0:global_reasons.append('NO_CASH_CAPACITY')
    plans=[]
    for row in mapping['contracts']:
        quote=rules.quality(quotes[row['instrument_key']],row['quantity'],now,10,Decimal('2'))
        cost=int(((Decimal(quote['ask'])*row['quantity']+Decimal('100'))*100).to_integral_value(rounding=ROUND_CEILING))
        reasons=sorted(set(global_reasons+quote['reasons']))
        if cost>cash_evidence['half_cash_cap_cents']:reasons.append('HALF_CASH_CAP_EXCEEDED')
        contract=next(c for c in value['contracts'] if c['instrument_key']==row['instrument_key'])
        plans.append(dict(direction='BULLISH' if row['side']=='CE' else 'BEARISH',
            instrument=row['instrument_key'],contract=contract,quantity=row['quantity'],
            quote=quote,proposed_cost_cents=cost,half_cash_cap_cents=cash_evidence['half_cash_cap_cents'],
            reasons=sorted(set(reasons)),evidence_checks_passed=not reasons,
            bundle_fingerprint=digest(bundle),cash_capture_fingerprint=digest(cash),
            contract_fingerprint=digest(contract),quote_fingerprint=digest(quotes[row['instrument_key']]),
            price_basis='OBSERVED_ASK_PLUS_PROVISIONAL_INR100_BUFFER',
            tick_units_verified=False,executable_request_created=False,**FLAGS))
    return plans


@contextmanager
def readonly(path):
    p=Path(path)
    need(p.is_file() and not p.is_symlink(),'REGULAR_EXISTING_DATABASE_REQUIRED')
    db=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN');yield db
    finally:db.close()


def controller_check(controller_db,adapter_db,pin,*,as_of,expected_version,bridge_run_id,signal_at):
    """Current local control blockers, never a remote/atomic execution clearance."""
    reasons=[]
    need(Path(controller_db).resolve()!=Path(adapter_db).resolve(),'DISTINCT_SOURCE_DATABASES_REQUIRED')
    with readonly(controller_db) as c,readonly(adapter_db) as a:
        row=c.execute('SELECT data FROM control WHERE id=1').fetchone()
        need(row is not None,'CONTROLLER_CONTROL_REQUIRED')
        control=json.loads(row[0]);now=aware(as_of)
        if control['mode']!='ARMED':reasons.append('CONTROLLER_PAUSED')
        if control['version']!=expected_version:reasons.append('CONTROL_VERSION_MISMATCH')
        if control['session_date']!=day(now):reasons.append('CONTROL_SESSION_MISMATCH')
        if not control.get('reconciled') or not control.get('last_reconciled_at'):
            reasons.append('CONTROLLER_RECONCILIATION_REQUIRED')
        elif not 0<=(now-aware(control['last_reconciled_at'])).total_seconds()<=30:
            reasons.append('CONTROLLER_RECONCILIATION_STALE_OR_FUTURE')
        stop=c.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
        need(stop is not None,'DURABLE_STOP_STATE_REQUIRED')
        if stop[0]!=stop[1]:reasons.append('DURABLE_STOP_PENDING')
        signal=aware(signal_at)
        if day(signal)!=day(now) or not 0<=(now-signal).total_seconds()<=60:
            reasons.append('SIGNAL_STALE_FUTURE_OR_WRONG_SESSION')
        if not control.get('resumed_at') or signal<=aware(control['resumed_at']):
            reasons.append('PRE_RESUME_SIGNAL_NOT_ELIGIBLE')
        from market_lab.hilega_production_bridge_health_v1 import effective
        row=c.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()
        if row is None:reasons.append('BRIDGE_HEALTH_REQUIRED')
        else:
            health=json.loads(row[0])
            if not effective(health,now.astimezone(ZoneInfo('Asia/Kolkata')))['healthy']:
                reasons.append('BRIDGE_HEALTH_NOT_READY')
            if health.get('run_id')!=bridge_run_id:reasons.append('BRIDGE_LEASE_MISMATCH')
        for table in ('intents','sim_orders','sim_fills','sim_allocation_reservations'):
            if c.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                reasons.append('EXISTING_CONTROLLER_EXECUTION_OR_HOLD_REQUIRES_REVIEW')
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('staged_intents','staged_reservations','staged_adapter_requests'):
            if table in tables and c.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                reasons.append('EXISTING_STAGED_PREPARATION_REQUIRES_REVIEW')
        meta=a.execute('SELECT data FROM meta WHERE id=1').fetchone()
        need(meta is not None and json.loads(meta[0])==dict(scope=pin['scope'],mode='LIVE_CLOSED'),
             'ADAPTER_SCOPE_OR_MODE_MISMATCH')
        for table in ('requests','attempts','receipts'):
            if a.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                reasons.append('EXISTING_ADAPTER_ACTIVITY_REQUIRES_REVIEW')
    return dict(reasons=sorted(set(reasons)),control_version=control['version'],
                control_mode=control['mode'],current_source_check_only=True,
                real_broker_reconciliation_verified=False)


def evaluate(bundle,pin,*,direction,as_of,controller_db,adapter_db,
             expected_version,bridge_run_id,signal_at):
    result=dict(FLAGS,model='HILEGA_EVIDENCE_PREFLIGHT_V1',assessed_at=as_of,
                production_ready=False,controller_integration_installed=False,
                debit_attribution='NOT_VALIDATED',thresholds_approved_for_production=False)
    try:
        need(direction in {'BULLISH','BEARISH'},'DIRECTION_REQUIRED')
        need(type(expected_version) is int,'CONTROL_VERSION_REQUIRED')
        plans=validate(bundle,pin,as_of=as_of)
        plan=next(p for p in plans if p['direction']==direction)
        controls=controller_check(controller_db,adapter_db,pin,as_of=as_of,
            expected_version=expected_version,bridge_run_id=bridge_run_id,signal_at=signal_at)
        reasons=sorted(set(plan['reasons']+controls['reasons']))
        return dict(result,status='READ_ONLY_PREFLIGHT_CHECKS_PASS' if not reasons else 'NOT_CLEARED',
                    reasons=reasons,evidence_checks_passed=plan['evidence_checks_passed'],
                    control_checks_passed=not controls['reasons'],preparation_preview=plan,controls=controls,
                    note='Read-only unsent preview; no intent, hold or executable request created')
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z0-9_]{1,120}',str(exc)) else 'SOURCE_SCHEMA_OR_EVIDENCE_INVALID'
        return dict(result,status='BLOCKED',reasons=[reason],preparation_preview=None,
                    evidence_checks_passed=False,control_checks_passed=False)

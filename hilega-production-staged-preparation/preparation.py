"""Isolated controller preparation integration. No submission or live ownership."""
import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from market_lab.hilega_production_foundation.core import Service, Store, SimBroker, Blocked, encode, money
from market_lab import hilega_production_bridge_health_v1 as health
from market_lab import hilega_sim_allocation_v1 as allocation

ROOT = Path(__file__).resolve().parent.parent
PURPOSE = 'ISOLATED_STAGED_PREPARATION_V1'
FLAGS = dict(orders_sent=False,production_execution_enabled=False,entry_permission=False,
             strategy_ownership_verified=False,real_funds_reservation_verified=False,
             reservation_release_permission=False,live_contract_verified=False)


def sha(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def need(value, reason):
    if not value:
        raise Blocked(reason)


def stamp(value):
    value = datetime.fromisoformat(value)
    need(value.tzinfo is not None, 'AWARE_TIMESTAMP_REQUIRED')
    return value


def fresh(value, now, seconds, reason):
    at = stamp(value).astimezone(now.tzinfo)
    need(at.date() == now.date() and 0 <= (now-at).total_seconds() <= seconds, reason)
    return at


def load_mapping():
    expected = json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for relative, fingerprint in expected.items():
        path = ROOT/relative
        need(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == fingerprint,
             'INSTALLED_DEPENDENCY_VERSION_MISMATCH')
    spec = importlib.util.spec_from_file_location(
        'hilega_staged_provider_mapping',ROOT/'hilega-production-broker-adapter-closed/provider_mapping.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Preparation:
    """Only fresh owned staging directories, never a running workspace DB path.

    Reuses installed Service command/control/stop and bridge-health implementations.
    Staged holds remain explicitly synthetic and separate from simulator allocations.
    """
    def __init__(self, directory, *, clock=None, reopen=False):
        self.mapping = load_mapping()
        raw = Path(directory)
        need(not raw.is_symlink(), 'SYMLINK_STAGE_DIRECTORY_REJECTED')
        self.directory = raw.resolve()
        self.path = self.directory/'controller-staging.sqlite'
        marker = self.directory/'STAGED_PREPARATION.json'
        expected = dict(purpose=PURPOSE,database=str(self.path),production_execution_enabled=False)
        if reopen:
            need(marker.is_file() and not marker.is_symlink() and self.path.is_file() and
                 not self.path.is_symlink(), 'EXISTING_STAGED_DIRECTORY_REQUIRED')
            need(json.loads(marker.read_text()) == expected, 'STAGE_SCOPE_MISMATCH')
        else:
            need(not self.directory.exists(), 'FRESH_STAGE_DIRECTORY_REQUIRED')
            self.directory.mkdir(parents=True,mode=0o700)
            fd = os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(expected,stream)
        self.store = Store(self.path)
        with self.store.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS staged_intents(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS staged_reservations(id TEXT PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS staged_adapter_requests(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            ''')
        # Installed startup behavior always pauses; never auto-resume on restart.
        self._service = Service(self.store,SimBroker(self.store),clock)
        self.checkpoint = lambda stage: None

    def status(self):
        with self.store.lock():
            result = self._service._status()
            with self.store.db() as db:
                holds = [json.loads(x[0]) for x in db.execute('SELECT data FROM staged_reservations')]
                count = db.execute('SELECT COUNT(*) FROM staged_intents').fetchone()[0]
            result.update(FLAGS)
            result.update(staged_intent_count=count,
                          staged_held_cents=sum(x['held_cents'] for x in holds),
                          evidence_mode='EXPLICIT_STAGED_FIXTURE',
                          label='STAGED_PREPARED_UNSENT' if count else 'STAGED_'+result['label'])
            return result

    def command(self, action, **kwargs):
        need(action in {'pause','reconcile','resume'}, 'STAGE_SUPPORTS_PAUSE_RECONCILE_RESUME_ONLY')
        # Keep one installed control flock across gate and installed command.
        # Service.command obtains this flock itself; the stage transaction below
        # pauses atomically on prepare, and no code here releases staged holds.
        if action in {'resume','reconcile'}:
            with self.store.db() as db:
                pending = db.execute('SELECT COUNT(*) FROM staged_intents').fetchone()[0]
            need(not pending, 'STAGED_PREPARATION_REMAINS_UNRESOLVED')
        result = self._service.command(action,**kwargs)
        # A concurrent prepare may commit between the check and command; recheck
        # under control lock and force PAUSED before returning any usable result.
        with self.store.lock():
            with self.store.db() as db:
                pending = db.execute('SELECT COUNT(*) FROM staged_intents').fetchone()[0]
            if pending:
                self._service._block('STAGED_PREPARATION_REMAINS_UNRESOLVED')
                need(action == 'pause', 'STAGED_PREPARATION_REMAINS_UNRESOLVED')
            result['status'] = self._service._status()
        return dict(result,**FLAGS)

    def prepare(self, *, signal_id,signal_at,direction,contract,contract_at,quote,
                expected_version,session_date,bridge_run_id):
        need(isinstance(signal_id,str) and bool(signal_id) and len(signal_id)<=200,
             'SIGNAL_ID_REQUIRED')
        need(direction in {'BULLISH','BEARISH'}, 'DIRECTION_REQUIRED')
        need(type(expected_version) is int, 'CONTROL_VERSION_REQUIRED')
        payload = dict(signal_id=signal_id,signal_at=signal_at,direction=direction,
                       contract=contract,contract_at=contract_at,quote=quote,
                       expected_version=expected_version,session_date=session_date,
                       bridge_run_id=bridge_run_id)
        # Freeze the caller plan before fingerprinting or validating it.
        payload = json.loads(encode(payload))
        contract, quote = payload['contract'], payload['quote']
        fingerprint = sha(payload)
        sid = sha(dict(session_date=session_date,signal_id=signal_id))
        with self.store.lock():
            now = self._service.now()
            c = self._service._session()
            need(c['session_date']==session_date, 'SESSION_MISMATCH')
            with self.store.db() as db:
                prior = db.execute('SELECT fingerprint,data FROM staged_intents WHERE id=?',(sid,)).fetchone()
            if prior:
                need(prior[0]==fingerprint, 'SIGNAL_PAYLOAD_CONFLICT')
                # Historical response only: no current eligibility and no new hold.
                return dict(FLAGS,status='HISTORICAL_PREPARED_REPLAY',id=sid,
                            historical_only=True,current_control_mode=c['mode'])
            need(c['version']==expected_version, 'STALE_CONTROL_VERSION')
            need(c['mode']=='ARMED' and not self.store.stop_state()['pending'], 'TRADING_PAUSED_OR_STOP_PENDING')
            self._service._check_fresh(c)
            state = health.summary(self.store,now)
            need(state['required'] and state['healthy'], 'STAGED_BRIDGE_HEALTH_REQUIRED')
            health.assert_ready(self.store,now,run_id=bridge_run_id,submitting=True)
            signal = fresh(signal_at,now,60,'SIGNAL_STALE_FUTURE_OR_WRONG_SESSION')
            need('resumed_at' in c and signal>stamp(c['resumed_at']), 'PRE_RESUME_SIGNAL_NOT_ELIGIBLE')
            fresh(contract_at,now,30,'CONTRACT_STALE_FUTURE_OR_WRONG_SESSION')
            fresh(quote['at'],now,5,'QUOTE_STALE_FUTURE_OR_WRONG_SESSION')
            instrument = contract['instrument_key']
            need(isinstance(instrument,str) and re.fullmatch(r'NSE_FO\|[0-9]+',instrument),
                 'EXACT_BROKER_INSTRUMENT_REQUIRED')
            need(quote['instrument']==instrument, 'QUOTE_INSTRUMENT_MISMATCH')
            need(contract['instrument_type']==('CE' if direction=='BULLISH' else 'PE'),
                 'CONTRACT_DIRECTION_MISMATCH')
            need(quote.get('evidence_mode')=='EXPLICIT_STAGED_FIXTURE', 'STAGED_QUOTE_EVIDENCE_REQUIRED')
            bid,ask,tick = (money(quote[k]) for k in ('bid','ask','tick_rupees'))
            need(bid>0 and ask>=bid and tick>0, 'INVALID_QUOTE_OR_TICK')
            # Draft staging threshold, not an approved production quote policy.
            need((ask-bid)/ask<=Decimal('0.05'), 'STAGED_SPREAD_LIMIT_EXCEEDED')
            limit = (ask/tick).to_integral_value(rounding=ROUND_CEILING)*tick
            draft = self.mapping.draft(contract,request_id=sid,side='BUY',lots=1,
                as_of=now.isoformat(),order_type='LIMIT',limit_price=limit,normalized_tick_rupees=tick)
            quantity = draft['body']['quantity']
            config = allocation.config(self.store)
            need(config is not None and config.get('required') is True and
                 config.get('funds',{}).get('evidence_mode')=='EXPLICIT_SYNTHETIC_FIXTURE',
                 'SYNTHETIC_STAGE_FUNDS_REQUIRED')
            funds = config['funds']
            fresh(funds['at'],now,30,'FUNDS_STALE_FUTURE_OR_WRONG_SESSION')
            budget = int((money(funds['cash'])*Decimal('0.5')*100).to_integral_value(rounding=ROUND_FLOOR))
            held = int(((limit*quantity+money(config['buffer']))*100).to_integral_value(rounding=ROUND_CEILING))
            need(held>0 and held<=budget, 'STAGED_HALF_CASH_CAP_EXCEEDED')
            intent = dict(id=sid,signal_id=signal_id,signal_at=signal_at,direction=direction,
                instrument=instrument,quantity=quantity,side='BUY',filled=0,status='PREPARED_UNSENT',
                session_date=session_date,created_at=now.isoformat(),control_version=expected_version,
                evidence_mode='EXPLICIT_STAGED_FIXTURE',**FLAGS)
            hold = dict(id=sid,instrument=instrument,quantity=quantity,held_cents=held,
                amount_cents=held,created_at=now.isoformat(),state='STAGED_RESERVED_UNSENT',
                evidence_mode='EXPLICIT_STAGED_FIXTURE',real_funds_reservation_verified=False)
            request = dict(request_id=sid,draft=draft,signal_id=signal_id,signal_at=signal_at,
                direction=direction,reservation_reference=sid,evidence_mode='EXPLICIT_STAGED_FIXTURE',
                production_execution_enabled=False,transport_available=False)
            self.checkpoint('BEFORE_ATOMIC_TRANSACTION')
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
                stop = db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
                need(current==c and current['mode']=='ARMED' and stop[0]==stop[1], 'CONTROL_CHANGED_OR_STOP_PENDING')
                need(not db.execute('SELECT 1 FROM staged_intents LIMIT 1').fetchone(), 'STAGED_PREPARATION_REMAINS_UNRESOLVED')
                need(not any(db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone()
                    for table in ('intents','sim_orders','sim_fills','sim_allocation_reservations')),
                    'LEGACY_SIMULATOR_STATE_CANNOT_MIX')
                # Recheck the clock after lock/DB waits, not just at method entry.
                commit_now = self._service.now()
                need(commit_now.date().isoformat()==session_date, 'SESSION_CHANGED_BEFORE_COMMIT')
                self._service._check_fresh(current)
                fresh(signal_at,commit_now,60,'SIGNAL_STALE_FUTURE_OR_WRONG_SESSION')
                fresh(contract_at,commit_now,30,'CONTRACT_STALE_FUTURE_OR_WRONG_SESSION')
                fresh(quote['at'],commit_now,5,'QUOTE_STALE_FUTURE_OR_WRONG_SESSION')
                fresh(funds['at'],commit_now,30,'FUNDS_STALE_FUTURE_OR_WRONG_SESSION')
                # Re-read all mutable admission evidence within the transaction.
                stored_health = db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()
                need(stored_health is not None and health.effective(json.loads(stored_health[0]),commit_now)['healthy'] and
                     json.loads(stored_health[0])['run_id']==bridge_run_id, 'BRIDGE_EVIDENCE_CHANGED')
                stored_config = db.execute('SELECT data FROM sim_allocation_config WHERE id=1').fetchone()
                need(stored_config is not None and json.loads(stored_config[0])==config, 'FUNDS_EVIDENCE_CHANGED')
                db.execute('INSERT INTO staged_intents VALUES(?,?,?)',(sid,fingerprint,encode(intent)))
                self.checkpoint('AFTER_INTENT_INSERT')
                db.execute('INSERT INTO staged_reservations VALUES(?,?)',(sid,encode(hold)))
                self.checkpoint('AFTER_RESERVATION_INSERT')
                db.execute('INSERT INTO staged_adapter_requests VALUES(?,?)',(sid,encode(request)))
                current.update(mode='PAUSED',version=current['version']+1,reconciled=False,
                               reason='STAGED_PREPARATION_COMMITTED_SUBMISSION_DISABLED')
                db.execute('UPDATE control SET data=? WHERE id=1',(encode(current),))
                db.execute('INSERT INTO events(data) VALUES(?)',(encode(dict(type='STAGED_PREPARATION_COMMITTED',
                    at=now.isoformat(),intent_id=sid,reserved_cents=held,production_execution_enabled=False)),))
                self.checkpoint('BEFORE_COMMIT')
            self.checkpoint('AFTER_COMMIT')
            return dict(FLAGS,status='STAGED_PREPARED_UNSENT',id=sid,reserved_cents=held,
                        quantity=quantity,instrument=instrument,historical_only=False)

    def submit(self, *args, **kwargs):
        raise Blocked('STAGED_SUBMISSION_DISABLED_IN_CODE')

    def cancel(self, *args, **kwargs):
        raise Blocked('STAGED_CANCEL_AND_RELEASE_NOT_IMPLEMENTED')

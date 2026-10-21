"""Separate-process, GET/stream-only HILEGA policy observation integration.

The SDK callback only enqueues decoded messages. Disk, REST and evaluation
run in this process's main thread, never in the Sandbox worker.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import queue
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import dotenv_values
from filelock import FileLock
from observer import Config, Evaluator, Store, MODEL, POLICY, dumps, fingerprint, stamp
from active_marks import display_keys, publish as publish_active_marks

IST = ZoneInfo('Asia/Kolkata')
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/live-observation/hilega-strike-observation-v1'
AUDIT = ROOT / 'data/live-observation/hilega-directional-v1/step-audit.jsonl'
UNDERLYING = 'NSE_INDEX|Nifty 50'
ENTRIES = {
    'ENTRY_OPENING_BULLISH_CONFIRMED': 'BULLISH',
    'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21': 'BULLISH',
    'ENTRY_PATH1_ROUTE_B_STRUCTURAL': 'BULLISH',
    'ENTRY_OPENING_BEARISH_CONFIRMED': 'BEARISH',
    'ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21': 'BEARISH',
    'ENTRY_BEARISH_ROUTE_B_STRUCTURAL': 'BEARISH',
}


def now():
    return datetime.now(timezone.utc)


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as f:
        f.write(dumps(value))
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def append(path, value):
    with path.open('a') as f:
        f.write(dumps(value) + '\n')
        f.flush()
        os.fsync(f.fileno())


def load_settings(path):
    raw = json.loads(path.read_text())
    missing = []
    try:
        limits = Config(raw.get('limits') or {})
    except (ValueError, TypeError, KeyError):
        limits = None
        missing.append('VALID_POLICY_LIMITS_AND_CONFIRMED_GREEK_UNITS')
    required = ('holding_minutes', 'expected_move_points', 'iv_change_percentage_points',
                'invalidation_distance_points')
    scenario = raw.get('scenario') or {}
    for name in required:
        v = scenario.get(name)
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or (name != 'iv_change_percentage_points' and v <= 0):
            missing.append('SCENARIO_' + name.upper())
    velocity = raw.get('velocity') or {}
    minutes = velocity.get('lookback_minutes')
    minimum = velocity.get('min_directional_points_per_minute')
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 30:
        missing.append('VELOCITY_LOOKBACK_MINUTES_1_TO_30')
    if isinstance(minimum, bool) or not isinstance(minimum, (float, int)) or not math.isfinite(minimum) or minimum <= 0:
        missing.append('VELOCITY_MIN_DIRECTIONAL_POINTS_PER_MINUTE')
    if raw.get('iv_unit') not in ('FRACTION', 'PERCENTAGE_POINTS'):
        missing.append('CONFIRMED_UPSTOX_FEED_IV_UNIT')
    return raw, limits, missing


def velocity_context(closes, at, direction, rule):
    steps = rule['lookback_minutes']
    keys = [(at - timedelta(minutes=i)).isoformat() for i in range(steps+1)]
    # Decisions are stored with timezone-normalized UTC keys.
    if any(key not in closes for key in keys):
        return False, dict(reason='EXACT_COMPLETED_MINUTE_PATH_MISSING', required=keys)
    sign = 1 if direction == 'BULLISH' else -1
    rate = sign * (closes[keys[0]] - closes[keys[-1]]) / steps
    return rate >= rule['min_directional_points_per_minute'], dict(
        method='COMPLETED_NIFTY_CLOSE_CHANGE_PER_MINUTE', directional_rate=rate,
        required=rule['min_directional_points_per_minute'], lookback_minutes=steps)


def manifest(catalog, spot, direction, day):
    valid = [c for c in catalog if str(c.get('expiry', '')) >= day]
    if not valid:
        raise ValueError('NO_NONEXPIRED_OPTION_CATALOG')
    expiry = min(c['expiry'] for c in valid)
    lower = math.floor(spot / 50) * 50
    atm = min((lower, lower+50), key=lambda x: (abs(x-spot), x))
    side = 'CE' if direction == 'BULLISH' else 'PE'
    result = []
    for role in range(-5, 6):
        rows = [c for c in valid if c['expiry'] == expiry and c.get('instrument_type') == side and float(c['strike_price']) == atm+50*role]
        if len(rows) != 1:
            raise ValueError('EXACT_ELEVEN_CONTRACTS_UNAVAILABLE')
        c = rows[0]
        lot = int(c['lot_size'])
        if lot <= 0:
            raise ValueError('INVALID_LOT_SIZE')
        result.append(dict(instrument_key=c['instrument_key'], strike=atm+50*role,
                           option_type=side, expiry=expiry, lot_size=lot,
                           expiry_close_timestamp=expiry+'T15:30:00+05:30'))
    if len({c['instrument_key'] for c in result}) != 11:
        raise ValueError('DUPLICATE_CONTRACT_IDENTITY')
    return result


def feed_body(feed):
    return feed.get('firstLevelWithGreeks') or feed.get('fullFeed', {}).get('marketFF') or {}


class BlockedEvaluator:
    c = {'max_open_observations': 1}
    def __init__(self, missing):
        self.missing = missing
    def evaluate(self, event, current):
        return dict(model=MODEL, policy_version=POLICY, timestamp=current.isoformat(),
                    entry_timestamp=event['context']['signal_timestamp'], event_id=event['event_id'],
                    observation_id=event['observation_id'], signal=event['context']['direction'],
                    spot=event['context']['spot'], verdict='NOT_EVALUABLE',
                    reason='CONFIGURATION_REQUIRED', missing_inputs=self.missing,
                    top5=[], rejections=[], observation_only=True, order_enabled=False)


class Publisher:
    def __init__(self, config_path):
        DATA.mkdir(parents=True, exist_ok=True)
        self.raw, self.limits, self.missing = load_settings(config_path)
        self.engine = BlockedEvaluator(self.missing) if self.missing else Evaluator(self.limits)
        self.state_path = DATA/'publisher-state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else dict(
            offset=0, sequence=0, previous_hash=None, closes={}, pending={}, deliveries={})
        self.store = Store(DATA/'observer.sqlite3', DATA/'shadow_strike_obs.jsonl')
        self.cache = {}
        self.messages = queue.Queue(maxsize=2048)
        self.drops = 0
        self.streamer = None
        self.connected = False
        self.subscribed = set()
        self.catalog = []
        self.catalog_at = 0
        self.last_mark = 0
        self.stopping = False
        self.last_report = 0

    def save(self):
        atomic(self.state_path, self.state)

    def report(self, status, **extra):
        atomic(DATA/'collector-status.json', dict(timestamp=now().isoformat(), pid=os.getpid(),
               status=status, observation_only=True, execution_enabled=False,
               config_missing=self.missing, stream_connected=self.connected,
               cached_instruments=len(self.cache), dropped_feed_messages=self.drops,
               pending_entries=len(self.state['pending']), **extra))

    def prune(self):
        cutoff = now()-timedelta(hours=2)
        self.state['closes'] = {k:v for k,v in self.state['closes'].items() if stamp(k) >= cutoff}

    def emit(self, event):
        # Freeze before append. Replays reuse the exact event and event ID.
        eid = event['event_id']
        self.state['deliveries'].setdefault(eid, event)
        self.save()
        self.flush_deliveries()

    def flush_deliveries(self):
        for eid, event in list(self.state['deliveries'].items()):
            append(DATA/'input.jsonl', event)
            self.store.commit(event, {'integration_event_id': eid}, self.engine, now())
            del self.state['deliveries'][eid]
            self.save()

    def start_stream(self):
        import upstox_client
        env = dotenv_values(ROOT/'.env')
        token = os.getenv('UPSTOX_ACCESS_TOKEN') or env.get('UPSTOX_ACCESS_TOKEN')
        if not token:
            raise ValueError('UPSTOX_ANALYTICS_TOKEN_MISSING')
        # This client is used only for read-only contract lookup.
        self.rest = httpx.Client(base_url='https://api.upstox.com',
                                 headers={'Authorization': 'Bearer '+token}, timeout=15)
        cfg = upstox_client.Configuration()
        cfg.access_token = token
        self.streamer = upstox_client.MarketDataStreamerV3(upstox_client.ApiClient(cfg), [], 'full')
        def message(value):
            try:
                self.messages.put_nowait(value)
            except queue.Full:
                self.drops += 1
        self.streamer.on('message', message)
        self.streamer.on('open', lambda: self.stream_open())
        self.streamer.on('close', lambda *args: self.stream_closed())
        self.streamer.on('error', lambda *args: self.stream_closed())
        self.streamer.auto_reconnect(True, 5, 20)
        self.streamer.connect()

    def stream_open(self):
        self.connected = True
        self.subscribed = set()

    def stream_closed(self):
        self.connected = False
        # Tick data remains timestamped and expires; no synthetic heartbeat marks.

    def drain(self):
        for _ in range(2048):
            try:
                raw = self.messages.get_nowait()
            except queue.Empty:
                break
            message = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(message, dict) or message.get('currentTs') is None:
                continue
            if message.get('type') not in ('live_feed', 0, 'live_feed_update', 1):
                continue
            at = datetime.fromtimestamp(float(message['currentTs'])/1000, timezone.utc)
            if at > now()+timedelta(seconds=1):
                continue
            for key, feed in (message.get('feeds') or {}).items():
                old = self.cache.get(key)
                if old and stamp(old['at']) > at:
                    continue
                body = feed_body(feed)
                if body:
                    self.cache[key] = dict(feed=feed, at=at.isoformat())

    def subscribe(self):
        if not self.connected:
            return
        keys = {c['instrument_key'] for p in self.state['pending'].values() for c in p.get('contracts', [])}
        for (raw,) in self.store.db.execute('SELECT frame FROM state WHERE is_open=1'):
            keys.update(r['instrument_key'] for r in json.loads(raw)['top5'])
        keys.update(display_keys(self))
        additions = keys-self.subscribed
        removed = self.subscribed-keys
        if additions:
            self.streamer.subscribe(sorted(additions), 'full')
        if removed:
            self.streamer.unsubscribe(sorted(removed))
            for key in removed:
                self.cache.pop(key, None)
        self.subscribed = keys

    def read_audit(self):
        if not AUDIT.exists():
            return
        with AUDIT.open('rb') as f:
            stat = os.fstat(f.fileno())
            identity = [stat.st_dev, stat.st_ino]
            if self.state.get('source_identity') not in (None, identity) or stat.st_size < self.state['offset']:
                raise ValueError('AUDIT_REPLACED_OR_TRUNCATED')
            self.state['source_identity'] = identity
            f.seek(self.state['offset'])
            for _ in range(500):
                line = f.readline(2*1024*1024+1)
                if len(line) > 2*1024*1024:
                    raise ValueError('AUDIT_RECORD_TOO_LARGE')
                if not line.endswith(b'\n'):
                    break
                row = json.loads(line)
                core = {k:v for k,v in row.items() if k != 'record_hash'}
                expected = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode()).hexdigest()
                if row.get('sequence') != self.state['sequence']+1 or row.get('previous_hash') != self.state['previous_hash'] or row.get('record_hash') != expected:
                    raise ValueError('AUDIT_CHAIN_INVALID')
                self.on_row(row)
                self.state.update(offset=f.tell(), sequence=row['sequence'], previous_hash=row['record_hash'])
            self.save()

    def on_row(self, row):
        payload = row.get('payload') or {}
        at = payload.get('decision_timestamp') or row.get('checkpoint') or row.get('event_time')
        if not at:
            return
        current_session = stamp(at).astimezone(IST).date() == now().astimezone(IST).date()
        stage = row.get('stage')
        if stage == 'COMBINED_PRICE_OBSERVATION':
            if payload.get('strategy_id')=='HILEGA_V2_ALIGNMENT_DUAL_EXIT' and current_session and row.get('status')=='PROCESSED' and payload.get('nifty_close') is not None:
                self.state['closes'][stamp(at).astimezone(timezone.utc).isoformat()]=float(payload['nifty_close'])
            return
        if stage == 'DIRECTIONAL_DECISION':
            if payload.get('strategy_id') != 'HILEGA_V2_ALIGNMENT_DUAL_EXIT':
                return
            close = payload.get('nifty_close')
            if close is not None and current_session:
                self.state['closes'][stamp(at).astimezone(timezone.utc).isoformat()] = float(close)
            if row.get('status') != 'PROCESSED':
                return
            before, after = payload.get('trade_owner_before'), payload.get('trade_owner_after')
            events = payload.get('accepted_events') or []
            if before in ('BULLISH', 'BEARISH') and (after != before or any('EXIT' in e for e in events)):
                self.request_exit(before, at, 'STRATEGY_EXIT')
            if not current_session:
                return
            for event in events:
                if event not in ENTRIES:
                    continue
                direction = ENTRIES[event]
                oid = 'HILEGA-POLICY-'+fingerprint({'time':at,'direction':direction})[:24]
                if oid in self.state['pending'] or self.store.db.execute('SELECT 1 FROM state WHERE id=?',(oid,)).fetchone():
                    continue
                if close is None:
                    raise ValueError('CONFIRMED_SIGNAL_SPOT_MISSING')
                context = dict(direction=direction, signal_confirmed=True, velocity_confirmed=False,
                               signal_timestamp=at, spot=float(close), strategy_version=payload.get('strategy_version'),strategy_policy_id=payload.get('policy_id'))
                self.state['pending'][oid] = dict(context=context, audit_sequence=row['sequence'], event_type=event)
        elif stage == 'DIRECTIONAL_SESSION_CUTOFF' and row.get('status') == 'PROCESSED':
            for direction in ('BULLISH', 'BEARISH'):
                self.request_exit(direction, at, 'STRATEGY_CUTOFF')
        elif stage == 'DIRECTIONAL_MANUAL_EXIT_RESET' and row.get('status') == 'PROCESSED':
            # Coordinator emits this only after verified manual close/reset.
            for direction in ('BULLISH', 'BEARISH'):
                self.request_exit(direction, at, 'VERIFIED_MANUAL_EXIT_RESET')

    def request_exit(self, direction, at, reason):
        for pending in self.state['pending'].values():
            if pending['context']['direction'] == direction:
                pending['ended_before_selection'] = at
        exits = self.state.setdefault('exits', {})
        for oid, raw in self.store.db.execute('SELECT id,frame FROM state WHERE is_open=1'):
            if json.loads(raw)['signal'] == direction:
                exits[oid] = dict(requested_at=at, reason=reason)

    def prepare_entries(self):
        for oid, pending in list(self.state['pending'].items()):
            context = pending['context']
            age = (now()-stamp(context['signal_timestamp'])).total_seconds()
            if self.missing:
                self.emit(dict(type='SNAPSHOT', event_id=oid+'-ENTRY', observation_id=oid, context=context))
                del self.state['pending'][oid]
                self.save()
                continue
            if age < 0:
                continue
            if pending.get('ended_before_selection') or age > self.limits['max_signal_age_seconds']:
                context['observation_block_reason'] = ('STRATEGY_ENDED_BEFORE_SELECTION'
                    if pending.get('ended_before_selection') else 'STALE_SIGNAL_NO_RETROACTIVE_ENTRY')
                self.emit(dict(type='SNAPSHOT', event_id=oid+'-ENTRY', observation_id=oid, context=context))
                del self.state['pending'][oid]
                self.save()
                continue
            velocity, evidence = velocity_context(self.state['closes'], stamp(context['signal_timestamp']).astimezone(timezone.utc), context['direction'], self.raw['velocity'])
            context['velocity_confirmed'] = velocity
            context['velocity_evidence'] = evidence
            if not velocity:
                self.emit(dict(type='SNAPSHOT', event_id=oid+'-ENTRY', observation_id=oid, context=context))
                del self.state['pending'][oid]
                self.save()
                continue
            if 'contracts' not in pending:
                if time.monotonic()-self.catalog_at > 300:
                    response = self.rest.get('/v2/option/contract', params={'instrument_key': UNDERLYING})
                    response.raise_for_status()
                    body = response.json()
                    if body.get('status') != 'success':
                        raise ValueError('CONTRACT_CATALOG_REJECTED')
                    self.catalog, self.catalog_at = body['data'], time.monotonic()
                pending['contracts'] = manifest(self.catalog, context['spot'], context['direction'], now().astimezone(IST).date().isoformat())
                self.save()
                self.subscribe()
            keys = [c['instrument_key'] for c in pending['contracts']]
            if any(k not in self.cache for k in keys):
                continue
            if any(not 0 <= (now()-stamp(self.cache[k]['at'])).total_seconds() <= min(self.limits['max_quote_age_seconds'],self.limits['max_greeks_age_seconds']) for k in keys):
                continue
            scenario = self.raw['scenario']
            context.update(expected_move_points=scenario['expected_move_points'], holding_minutes=scenario['holding_minutes'],
                           iv_change_percentage_points=scenario['iv_change_percentage_points'],
                           invalidation_spot=context['spot']+(-1 if context['direction']=='BULLISH' else 1)*scenario['invalidation_distance_points'])
            metadata = []
            for contract in pending['contracts']:
                tick = self.cache[contract['instrument_key']]
                body = feed_body(tick['feed'])
                if body.get('iv') is None:
                    raise ValueError('FEED_IV_MISSING')
                iv = float(body['iv'])*(100 if self.raw['iv_unit']=='FRACTION' else 1)
                metadata.append(dict(contract, feed_tick_timestamp=tick['at'], iv_timestamp=tick['at'], iv=iv,
                                     theta_unit=self.limits['theta_unit'], vega_unit=self.limits['vega_unit']))
            self.emit(dict(type='SNAPSHOT', format='UPSTOX_V3_DECODED', event_id=oid+'-ENTRY', observation_id=oid,
                           context=context, contracts=metadata, source_audit_sequence=pending['audit_sequence'],
                           publisher_settings=self.raw,
                           payload=dict(currentTs=int(now().timestamp()*1000), feeds={k:self.cache[k]['feed'] for k in keys})))
            del self.state['pending'][oid]
            self.save()

    def marks(self):
        if time.monotonic()-self.last_mark < 5:
            return
        self.last_mark = time.monotonic()
        for oid, raw in list(self.store.db.execute('SELECT id,frame FROM state WHERE is_open=1')):
            frame = json.loads(raw)
            quotes = []
            for row in frame['top5']:
                tick = self.cache.get(row['instrument_key'])
                if not tick:
                    continue
                body = feed_body(tick['feed'])
                depth = body.get('firstDepth') or (body.get('marketLevel',{}).get('bidAskQuote') or [{}])[0]
                if all(k in depth for k in ('bidP','askP','bidQ')):
                    quotes.append(dict(instrument_key=row['instrument_key'], bid=depth['bidP'], ask=depth['askP'],
                                       bid_quantity=depth['bidQ'], quote_timestamp=tick['at'], price_evidence_source='RECORDED_FEED_UPDATE'))
            exit_info = self.state.setdefault('exits',{}).get(oid)
            kind = 'EXIT' if exit_info else 'MARK'
            event = dict(type=kind, event_id=oid+'-'+kind+'-'+fingerprint(quotes)[:24], observation_id=oid, quotes=quotes)
            if exit_info:
                event['strategy_exit'] = exit_info
            self.emit(event)

    def run(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: setattr(self,'stopping',True))
        self.flush_deliveries()
        try:
            if not self.missing:
                self.start_stream()
            while not self.stopping:
                try:
                    self.drain()
                    publish_active_marks(self)
                    self.read_audit()
                    self.prepare_entries()
                    if self.streamer:
                        self.subscribe()
                        self.marks()
                    if time.monotonic()-self.last_report >= 5:
                        self.prune()
                        self.report('CONFIGURATION_REQUIRED' if self.missing else 'RUNNING')
                        self.last_report = time.monotonic()
                except Exception as exc:
                    # Never log tokens, authorized WebSocket URLs or SDK errors.
                    message = str(exc)
                    code = message if isinstance(exc,ValueError) and message.replace('_','').isalpha() and message.isupper() else None
                    self.report('DATA_OR_EVALUATION_ERROR', error_type=type(exc).__name__, reason=code)
                time.sleep(1)
        finally:
            if self.streamer:
                self.streamer.disconnect()
            if hasattr(self,'rest'):
                self.rest.close()
            self.save()
            self.store.close()
            self.report('STOPPED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'hilega_policy_live/config.json')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    raw, limits, missing = load_settings(args.config)
    if args.check:
        import importlib.util
        print(dumps(dict(status='READY_FOR_VM_VALIDATION' if not missing else 'CONFIGURATION_REQUIRED',
                         missing_inputs=missing, upstox_sdk_installed=importlib.util.find_spec('upstox_client') is not None,
                         observation_only=True, execution_enabled=False)))
        return
    DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(DATA/'integration.lock'),timeout=0):
        Publisher(args.config).run()


if __name__ == '__main__':
    main()

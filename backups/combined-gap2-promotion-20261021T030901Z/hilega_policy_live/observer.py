"""HILEGA passive observer. Python 3.11+, standard library, Linux staging.

Run as a separate OS process. Input is an append-only JSONL feed spool owned
by a decoder/publisher, never by the Sandbox execution worker. No broker API,
credential, order method, strategy mutation or execution import exists here.
See README.md for the input contract and deployment boundaries.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import math
import os
import signal
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
MODEL = 'HILEGA_STRIKE_OBSERVATION_FRAME_V1'
POLICY = 'HILEGA_MAX_GAINS_SHADOW_1.0.0'
MAX_LINE = 1024 * 1024


def utc():
    return datetime.now(timezone.utc)


def stamp(value):
    """Only timezone-aware ISO timestamps; epoch feed times mapped by adapter."""
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return dt


def num(value):
    if isinstance(value, bool):
        raise ValueError('BOOLEAN_NUMBER')
    v = float(value)
    if not math.isfinite(v):
        raise ValueError('NONFINITE_NUMBER')
    return v


def reject_constant(value):
    raise ValueError('NONFINITE_JSON')


def loads(value):
    return json.loads(value, parse_constant=reject_constant)


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


class Config:
    """No guessed market thresholds. Operator must explicitly supply all limits."""
    def __init__(self, raw):
        self.raw = dict(raw)
        positive = ('max_quote_age_seconds', 'max_greeks_age_seconds',
                    'max_signal_age_seconds', 'max_spread_percent',
                    'premium_budget_rupees', 'max_open_observations')
        nonnegative = ('round_trip_cost_per_lot_rupees', 'slippage_points_per_side',
                       'gamma_shock_points', 'max_gamma_delta_change',
                       'max_theta_premium_fraction')
        for key in positive + nonnegative:
            self.raw[key] = num(raw[key])
            if self.raw[key] < 0 or (key in positive and self.raw[key] == 0):
                raise ValueError('INVALID_CONFIG:' + key)
        if not self.raw['max_open_observations'].is_integer():
            raise ValueError('INTEGER_OPEN_LIMIT_REQUIRED')
        if raw.get('theta_unit') != 'PREMIUM_POINTS_PER_CALENDAR_DAY':
            raise ValueError('THETA_UNITS_NOT_CONFIRMED')
        if raw.get('vega_unit') != 'PREMIUM_POINTS_PER_IV_PERCENTAGE_POINT':
            raise ValueError('VEGA_UNITS_NOT_CONFIRMED')
        self.hash = fingerprint(self.raw)

    def __getitem__(self, key):
        return self.raw[key]


class UpstoxAdapter:
    """Map option-chain REST JSON or decoded V3 feed JSON without inventing metadata.

    Feed mode requires a separate 11-contract manifest: a feed key has no
    reliable strike, expiry, lot size or IV-unit provenance in its key string.
    REST quotes require separately verified market-update timing evidence.
    """
    @staticmethod
    def contracts(event):
        payload = event['payload']
        metadata = event['contracts']
        if not isinstance(metadata, list) or len(metadata) != 11:
            raise ValueError('EXACT_ELEVEN_CONTRACT_MANIFEST_REQUIRED')
        result = []
        chain = {}
        if event['format'] == 'UPSTOX_CHAIN':
            if payload.get('status') != 'success':
                raise ValueError('UPSTOX_CHAIN_NOT_SUCCESS')
            for row in payload['data']:
                for side, key in (('CE', 'call_options'), ('PE', 'put_options')):
                    option = row.get(key)
                    if option:
                        identity = option['instrument_key']
                        if identity in chain:
                            raise ValueError('DUPLICATE_CHAIN_INSTRUMENT')
                        chain[identity] = (row, side, option)
        elif event['format'] != 'UPSTOX_V3_DECODED':
            raise ValueError('UNSUPPORTED_UPSTOX_FORMAT')
        for meta in metadata:
            r = dict(meta)
            key = meta['instrument_key']
            if event['format'] == 'UPSTOX_CHAIN':
                record, side, option = chain[key]
                if side != meta['option_type'] or num(record['strike_price']) != num(meta['strike']) or record['expiry'] != meta['expiry']:
                    raise ValueError('CHAIN_MANIFEST_IDENTITY_MISMATCH')
                market, greeks = option['market_data'], option['option_greeks']
                r.update(bid=market['bid_price'], ask=market['ask_price'],
                         bid_quantity=market['bid_qty'], ask_quantity=market['ask_qty'])
            else:
                feed = payload['feeds'][key]
                body = feed.get('firstLevelWithGreeks') or feed.get('fullFeed', {}).get('marketFF')
                if not body:
                    raise ValueError('OPTION_DEPTH_GREEKS_FEED_REQUIRED')
                depth = body.get('firstDepth')
                if depth is None:
                    depth = body['marketLevel']['bidAskQuote'][0]
                greeks = body['optionGreeks']
                r.update(bid=depth['bidP'], ask=depth['askP'],
                         bid_quantity=depth['bidQ'], ask_quantity=depth['askQ'])
                # currentTs is feed tick time, not an exchange book timestamp.
                # Aggregated snapshots carry the actual last tick for EACH
                # instrument. Never refresh a quiet leg with another leg's tick.
                tick = meta.get('feed_tick_timestamp') or datetime.fromtimestamp(num(payload['currentTs']) / 1000, timezone.utc).isoformat()
                r.update(quote_timestamp=tick, greeks_timestamp=tick,
                         price_evidence_source='RECORDED_FEED_UPDATE',
                         quote_timestamp_source='UPSTOX_FEED_TICK')
            for name in ('delta', 'gamma', 'theta', 'vega'):
                r[name] = greeks[name]
            if greeks.get('iv') is not None:
                r['iv'] = greeks['iv']
            result.append(r)
        return result


class Evaluator:
    def __init__(self, config):
        self.c = config

    def evaluate(self, event, now):
        context = event['context']
        frame = dict(model=MODEL, policy_version=POLICY, config_hash=self.c.hash,
                     timestamp=now.isoformat(timespec='microseconds'),
                     event_id=event['event_id'], observation_id=event['observation_id'],
                     entry_snapshot_id=fingerprint(event), entry_timestamp=now.isoformat(),
                     signal=context.get('direction'), spot=context.get('spot'),
                     verdict='NO_TRADE', reason=None, top5=[], rejections=[],
                     max_quote_age_seconds=self.c['max_quote_age_seconds'],
                     observation_only=True, order_enabled=False)
        frame['velocity_evidence'] = context.get('velocity_evidence')
        frame['signal_timestamp'] = context.get('signal_timestamp')
        frame['strategy_version'] = context.get('strategy_version')
        frame['publisher_settings'] = event.get('publisher_settings')
        if context.get('observation_block_reason'):
            frame.update(verdict='NOT_EVALUABLE', reason=context['observation_block_reason'])
            return frame
        if context.get('direction') not in ('BULLISH', 'BEARISH') or context.get('signal_confirmed') is not True or context.get('velocity_confirmed') is not True:
            frame['reason'] = 'SIGNAL_VELOCITY_INVALID'
            return frame
        signal_age = (now - stamp(context['signal_timestamp'])).total_seconds()
        if not 0 <= signal_age <= self.c['max_signal_age_seconds']:
            frame['reason'] = 'SIGNAL_STALE_OR_FUTURE'
            return frame
        side = 'CE' if context['direction'] == 'BULLISH' else 'PE'
        spot = num(context['spot'])
        move = num(context['expected_move_points'])
        minutes = num(context['holding_minutes'])
        iv_shift = num(context['iv_change_percentage_points'])
        invalidation = num(context['invalidation_spot'])
        if min(spot, move, minutes, invalidation) <= 0 or (invalidation >= spot if side == 'CE' else invalidation <= spot):
            raise ValueError('INVALID_SCENARIO_OR_INVALIDATION')
        frame['assumptions'] = dict(expected_move_points=move, holding_minutes=minutes,
                                    iv_change_percentage_points=iv_shift, invalidation_spot=invalidation,
                                    theta_unit=self.c['theta_unit'], vega_unit=self.c['vega_unit'],
                                    limits=self.c.raw, model='LOCALLY_CONSTANT_GREEKS')
        rows = UpstoxAdapter.contracts(event)
        lower = math.floor(spot / 50) * 50
        atm = min((lower, lower + 50), key=lambda s: (abs(s - spot), s))
        if {num(r['strike']) for r in rows} != {atm + 50*i for i in range(-5, 6)} or len({r['instrument_key'] for r in rows}) != 11 or len({r['expiry'] for r in rows}) != 1:
            raise ValueError('INVALID_ATM_PLUS_MINUS_FIVE_ARRAY')
        eligible = []
        for raw in rows:
            checks = []
            def check(name, observed, required, passed):
                checks.append(dict(name=name, observed=observed, required=required, result='PASS' if passed else 'FAIL'))
            try:
                r = {k: num(raw[k]) for k in ('strike', 'bid', 'ask', 'bid_quantity', 'ask_quantity', 'delta', 'gamma', 'theta', 'vega', 'iv', 'lot_size')}
                expiry = date.fromisoformat(raw['expiry'])
                dte = (expiry - now.astimezone(IST).date()).days
                lot = r['lot_size']
                check('SIGNAL', context['direction'], side, raw['option_type'] == side)
                check('EXPIRY', dte, 'DTE > 0', dte > 0)
                check('LOT_SIZE', lot, 'positive integer', lot > 0 and lot.is_integer())
                check('BID_ASK', [r['bid'], r['ask']], '0 < bid <= ask', 0 < r['bid'] <= r['ask'])
                spread = 100*(r['ask']-r['bid'])/r['ask'] if r['ask'] > 0 else None
                check('SPREAD_PERCENT', spread, self.c['max_spread_percent'], spread is not None and 0 <= spread <= self.c['max_spread_percent'])
                check('DEPTH', [r['bid_quantity'], r['ask_quantity']], lot, min(r['bid_quantity'], r['ask_quantity']) >= lot and all(r[k].is_integer() for k in ('bid_quantity', 'ask_quantity')))
                qage = (now-stamp(raw['quote_timestamp'])).total_seconds()
                gage = (now-stamp(raw['greeks_timestamp'])).total_seconds()
                check('QUOTE_AGE_SECONDS', qage, self.c['max_quote_age_seconds'], 0 <= qage <= self.c['max_quote_age_seconds'])
                check('GREEKS_AGE_SECONDS', gage, self.c['max_greeks_age_seconds'], 0 <= gage <= self.c['max_greeks_age_seconds'])
                check('QUOTE_PROVENANCE', raw.get('price_evidence_source'), ['MARKET_UPDATE', 'RECORDED_FEED_UPDATE'], raw.get('price_evidence_source') in ('MARKET_UPDATE', 'RECORDED_FEED_UPDATE'))
                check('GREEK_UNITS', [raw.get('theta_unit'), raw.get('vega_unit')], [self.c['theta_unit'], self.c['vega_unit']], raw.get('theta_unit') == self.c['theta_unit'] and raw.get('vega_unit') == self.c['vega_unit'])
                # Separate IV evidence is needed when V3 feed omits IV.
                ivage = (now-stamp(raw['iv_timestamp'])).total_seconds()
                check('IV_AGE_SECONDS', ivage, self.c['max_greeks_age_seconds'], 0 <= ivage <= self.c['max_greeks_age_seconds'])
                check('GREEKS_VALID', [r['gamma'], r['vega'], r['iv']], 'gamma >= 0; vega >= 0; IV > 0; shocked IV > 0', r['gamma'] >= 0 and r['vega'] >= 0 and r['iv'] > 0 and r['iv']+iv_shift > 0)
                check('DELTA_SIGN', r['delta'], side, (r['delta'] > 0 if side == 'CE' else r['delta'] < 0))
                check('DELTA_BAND', abs(r['delta']), [0.40, 0.52], 0.40 <= abs(r['delta']) <= 0.52)
                close = stamp(raw['expiry_close_timestamp'])
                check('HOLDING_BEFORE_EXPIRY', minutes*60, (close-now).total_seconds(), (close-now).total_seconds() > minutes*60 and close.astimezone(IST).date() == expiry)
                cost = self.c['round_trip_cost_per_lot_rupees'] + 2*self.c['slippage_points_per_side']*lot
                check('BUDGET', r['ask']*lot+cost, self.c['premium_budget_rupees'], r['ask']*lot+cost <= self.c['premium_budget_rupees'])
                failed = [f['name'] for f in checks if f['result'] == 'FAIL']
                if failed:
                    frame['rejections'].append(dict(strike=r['strike'], option_type=raw['option_type'], instrument_key=raw['instrument_key'], step='HARD_FILTERS', reasons=failed, filters=checks))
                    continue
                # Ask-entry/bid-exit basis: spread is deducted once in modeled
                # movement, not again in observed ask-to-bid P&L.
                signed_move = move if side == 'CE' else -move
                gross = r['delta']*signed_move + .5*r['gamma']*move**2 + r['theta']*minutes/1440 + r['vega']*iv_shift
                net = gross - (r['ask']-r['bid']) - cost/lot
                roi = 100*net/r['ask']
                for value in (gross, net, roi):
                    num(value)  # fail closed on overflow in modeled output
                shock = invalidation - spot
                invalid_change = r['delta']*shock + .5*r['gamma']*shock**2 + r['theta']*minutes/1440 + r['vega']*iv_shift
                value = max(0, r['bid']+invalid_change)
                num(value)
                flags = ['CONSTANT_GREEKS_MODEL_NOT_A_PROFIT_FORECAST']
                if max(r['gamma']*move, r['gamma']*abs(shock), r['gamma']*self.c['gamma_shock_points']) > self.c['max_gamma_delta_change']:
                    flags.append('LARGE_GAMMA_DELTA_CHANGE_MODEL_UNRELIABLE')
                if max(0, -r['theta'])*minutes/1440/r['ask'] > self.c['max_theta_premium_fraction']:
                    flags.append('THETA_HORIZON_RISK')
                eligible.append(dict(instrument_key=raw['instrument_key'], strike=r['strike'], option_type=side,
                    expiry=raw['expiry'], dte=dte, quantity=int(lot), state='OPEN',
                    delta=r['delta'], gamma=r['gamma'], theta=r['theta'], vega=r['vega'], iv=r['iv'],
                    entry_bid=r['bid'], entry_ask=r['ask'], entry_bid_quantity=r['bid_quantity'], entry_ask_quantity=r['ask_quantity'],
                    entry_spread_percent=spread, entry_quote_timestamp=raw['quote_timestamp'], entry_greeks_timestamp=raw['greeks_timestamp'],
                    quote_timestamp_source=raw.get('quote_timestamp_source', 'SUPPLIED_MARKET_UPDATE'),
                    modelled_net_gain_points=net, modelled_roi_percent=roi,
                    leverage_score=r['gamma']/r['ask'], delta_target_distance=abs(abs(r['delta'])-.45),
                    invalidation_modelled_premium=value, invalidation_modelled_change=value-r['ask'],
                    invalidation_modelled_net_rupees=(value-r['ask'])*lot-cost,
                    total_cost_rupees=cost, current_bid=r['bid'], current_bid_quantity=r['bid_quantity'],
                    current_ask=r['ask'], quote_timestamp=raw['quote_timestamp'],
                    price_evidence_source=raw['price_evidence_source'],
                    audit=dict(filters=checks, risk_flags=flags, favourable_conditions=[
                        f'Absolute Delta {abs(r["delta"])} is within 0.40–0.52',
                        f'Spread {spread}% is within {self.c["max_spread_percent"]}%',
                        f'Both sides have depth for one lot ({int(lot)})',
                        f'Net modelled ROI {roi}% under the frozen scenario'],
                        greek_liquidity_footprint={**r, 'quote_timestamp':raw['quote_timestamp'], 'greeks_timestamp':raw['greeks_timestamp'], 'iv_timestamp':raw['iv_timestamp'], 'evaluated_at':frame['timestamp']})))
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                required = ('strike', 'bid', 'ask', 'bid_quantity', 'ask_quantity', 'delta', 'gamma', 'theta', 'vega', 'iv', 'lot_size', 'expiry', 'option_type', 'quote_timestamp', 'greeks_timestamp', 'iv_timestamp', 'expiry_close_timestamp')
                missing = [k for k in required if raw.get(k) is None]
                frame['rejections'].append(dict(strike=raw.get('strike'), option_type=raw.get('option_type'), instrument_key=raw.get('instrument_key'), step='DATA_VALIDATION', reasons=['MISSING_OR_INVALID_DATA'], missing_fields=missing, error_type=type(exc).__name__, filters=checks))
        eligible.sort(key=lambda r: (-r['modelled_roi_percent'], -r['leverage_score'], r['delta_target_distance'], r['instrument_key']))
        if not eligible:
            frame['reason'] = 'ZERO_ELIGIBLE_CONTRACTS'
            return frame
        if eligible[0]['modelled_net_gain_points'] <= 0:
            frame['reason'] = 'NO_POSITIVE_MODELLED_NET_RETURN'
            frame['eligible_ranking'] = eligible
            return frame
        for i, row in enumerate(eligible[:5]):
            row['rank'] = i+1
            peer = eligible[i+1] if i+1 < len(eligible) else None
            reason = 'Only remaining eligible candidate'
            if peer:
                metric = next((k for k in ('modelled_roi_percent', 'leverage_score', 'delta_target_distance') if row[k] != peer[k]), 'instrument_key')
                reason = f'{metric}: {row[metric]} vs runner-up {peer["strike"]} {peer[metric]}'
            row['audit'].update(selection_reason='Eligible under the declared scenario; ordered by net ROI, Gamma/ask, distance to 0.45 Delta', rank_comparison=reason)
            if row['modelled_net_gain_points'] <= 0:
                row['audit']['risk_flags'].append('NONPOSITIVE_ALTERNATIVE_RETURN')
        frame.update(verdict='SELECTED_FOR_OBSERVATION', reason='HIGHEST_MODELLED_NET_ROI',
                     top5=eligible[:5], unfilled_slot_reason='Fewer than five eligible candidates; see exact filter failures')
        return frame


class Store:
    """SQLite transaction + durable JSONL outbox. One writer; restart safe.

    Pending frames are committed before append. On restart last journal sequence
    determines which outbox records remain. A partial final append is truncated
    under exclusive lock before retry. Never rotate/truncate the live journal.
    """
    def __init__(self, db_path, journal):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        journal.parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(str(journal)+'.lock', 'a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.journal = journal
        self.db = sqlite3.connect(db_path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY);
          CREATE TABLE IF NOT EXISTS state(id TEXT PRIMARY KEY, frame TEXT NOT NULL, is_open INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS outbox(seq INTEGER PRIMARY KEY AUTOINCREMENT, frame TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cursor(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        self.last_seq = 0
        if journal.exists():
            with journal.open('rb+') as f:
                while True:
                    start = f.tell(); line = f.readline()
                    if not line:
                        break
                    if not line.endswith(b'\n'):
                        f.seek(start); f.truncate(); f.flush(); os.fsync(f.fileno()); break
                    record = loads(line)
                    seq = record['journal_sequence']
                    if seq != self.last_seq+1:
                        raise ValueError('JOURNAL_SEQUENCE_OR_STATE_MISMATCH')
                    self.last_seq = seq
        maximum = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM outbox').fetchone()[0]
        if self.last_seq > maximum:
            raise ValueError('JOURNAL_HAS_NO_MATCHING_DATABASE')
        self.flush()

    def cursor(self):
        row = self.db.execute("SELECT value FROM cursor WHERE key='feed'").fetchone()
        return loads(row[0]) if row else None

    def commit(self, event, position, engine, now):
        """Event errors are logged, but storage errors fail this process closed."""
        eid = event.get('event_id') if isinstance(event, dict) else None
        if not isinstance(eid, str) or not eid or len(eid) > 256:
            eid = 'INVALID:' + fingerprint(position)
            event = dict(event_id=eid, type='INVALID')
        with self.db:
            if not self.db.execute('SELECT 1 FROM seen WHERE id=?', (eid,)).fetchone():
                try:
                    self.process(event, engine, now)
                except Exception as exc:
                    # Do not log arbitrary exception strings or raw payloads:
                    # those could contain upstream secrets.
                    if isinstance(exc, (sqlite3.Error, OSError)):
                        raise
                    code = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isupper() and str(exc).replace('_', '').isalpha() else 'EVENT_VALIDATION_FAILURE'
                    self.enqueue(dict(model=MODEL, timestamp=now.isoformat(), verdict='NOT_EVALUABLE',
                                      event_id=eid, reason=code, error_type=type(exc).__name__, top5=[], rejections=[]))
                self.db.execute('INSERT INTO seen VALUES (?)', (eid,))
            self.db.execute("INSERT OR REPLACE INTO cursor VALUES ('feed',?)", (dumps(position),))
        self.flush()

    def enqueue(self, frame):
        self.db.execute('INSERT INTO outbox(frame) VALUES (?)', (dumps(frame),))

    def process(self, event, engine, now):
        kind = event['type']
        oid = event.get('observation_id')
        if kind == 'SNAPSHOT':
            if not isinstance(oid, str) or not oid:
                raise ValueError('OBSERVATION_ID_REQUIRED')
            if self.db.execute('SELECT 1 FROM state WHERE id=?', (oid,)).fetchone():
                raise ValueError('OBSERVATION_ID_ALREADY_FROZEN')
            count = self.db.execute('SELECT COUNT(*) FROM state WHERE is_open=1').fetchone()[0]
            if count >= engine.c['max_open_observations']:
                raise ValueError('OPEN_OBSERVATION_CAPACITY')
            frame = engine.evaluate(event, now)
            self.db.execute('INSERT INTO state VALUES (?,?,?)', (oid, dumps(frame), int(bool(frame['top5']))))
            self.enqueue(frame)
        elif kind in ('MARK', 'EXIT'):
            record = self.db.execute('SELECT frame FROM state WHERE id=?', (oid,)).fetchone()
            if not record:
                raise ValueError('UNKNOWN_OBSERVATION')
            frame = loads(record[0])
            if not frame['top5'] or all(r['state']=='CLOSED' for r in frame['top5']):
                return  # no-position/duplicate exit is harmless
            quotes = event['quotes']
            if len({q['instrument_key'] for q in quotes}) != len(quotes):
                raise ValueError('DUPLICATE_MARK_QUOTE')
            by_key = {q['instrument_key']: q for q in quotes}
            frame.update(timestamp=now.isoformat(timespec='microseconds'), event_id=event['event_id'])
            if kind == 'EXIT':
                frame['strategy_exit'] = event.get('strategy_exit')
            for row in frame['top5']:
                if row['state'] == 'CLOSED':
                    continue
                q = by_key.get(row['instrument_key'])
                row.update(points=None, pnl_rupees=None, roi_percent=None, pnl_status='QUOTE_UNAVAILABLE')
                if not q:
                    row['current_bid'] = None
                    if kind == 'EXIT':
                        row['exit_requested_at'] = now.isoformat()
                    continue
                bid, ask, depth = (num(q[k]) for k in ('bid', 'ask', 'bid_quantity'))
                age = (now-stamp(q['quote_timestamp'])).total_seconds()
                evidence = q.get('price_evidence_source') in ('MARKET_UPDATE', 'RECORDED_FEED_UPDATE')
                oldtime = stamp(row['quote_timestamp'])
                spread = 100*(ask-bid)/ask if ask > 0 else None
                good = evidence and 0 <= age <= frame['max_quote_age_seconds'] and stamp(q['quote_timestamp']) >= oldtime and 0 < bid <= ask and depth >= row['quantity'] and spread <= frame['assumptions']['limits']['max_spread_percent']
                if not good:
                    row['current_bid'] = None
                    row['pnl_status'] = 'STALE_OR_UNVERIFIED_QUOTE'
                    if kind == 'EXIT':
                        row['exit_requested_at'] = now.isoformat()
                    continue
                close = kind == 'EXIT'
                row.update(current_bid=bid, current_ask=ask, current_bid_quantity=depth,
                           quote_timestamp=q['quote_timestamp'], price_evidence_source=q['price_evidence_source'])
                if close:
                    row.update(state='CLOSED', exit_bid=bid, exit_quote_timestamp=q['quote_timestamp'])
                    row.pop('exit_requested_at', None)
                row['points'] = bid-row['entry_ask']
                row['pnl_rupees'] = row['points']*row['quantity']-row['total_cost_rupees']
                row['roi_percent'] = 100*row['pnl_rupees']/(row['entry_ask']*row['quantity'])
                row['pnl_status'] = 'CLOSED_HYPOTHETICAL' if close else 'OPEN_HYPOTHETICAL'
            self.db.execute('UPDATE state SET frame=?,is_open=? WHERE id=?', (dumps(frame), int(any(r['state']=='OPEN' for r in frame['top5'])), oid))
            self.enqueue(frame)
        else:
            raise ValueError('UNSUPPORTED_EVENT_TYPE')

    def flush(self):
        with self.journal.open('ab', buffering=0) as f:
            for seq, raw in self.db.execute('SELECT seq,frame FROM outbox WHERE seq>? ORDER BY seq', (self.last_seq,)):
                frame = loads(raw); frame['journal_sequence'] = seq
                data = (dumps(frame)+'\n').encode()
                view = memoryview(data)
                while view:
                    written = f.write(view)
                    if not written:
                        raise OSError('SHORT_JOURNAL_WRITE')
                    view = view[written:]
                os.fsync(f.fileno())
                self.last_seq = seq

    def close(self):
        self.db.close()
        self.lock.close()


def next_event(path, cursor):
    """Never consume incomplete lines. Bound record size and reopen on rotation."""
    try:
        with path.open('rb') as f:
            stat = os.fstat(f.fileno())
            identity = [stat.st_dev, stat.st_ino]
            offset = cursor['offset'] if cursor and cursor['identity']==identity else 0
            if offset > stat.st_size:
                raise OSError('FEED_TRUNCATED_IN_PLACE')
            f.seek(offset)
            line = f.readline(MAX_LINE+1)
            if len(line) > MAX_LINE:
                raise OSError('FEED_RECORD_SIZE_LIMIT')
            if not line.endswith(b'\n'):
                return None
            position = dict(identity=identity, offset=f.tell())
            try:
                event = loads(line)
            except (ValueError, UnicodeError):
                event = dict(type='INVALID', event_id='INVALID:'+fingerprint(position))
            return event, position
    except FileNotFoundError:
        return None


async def run(args):
    config = Config(loads(args.config.read_text()))
    store = Store(args.state, args.journal)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    engine = Evaluator(config)
    try:
        while not stop.is_set():
            record = await asyncio.to_thread(next_event, args.feed, store.cursor())
            if record:
                event, position = record
                # Store uses SQLite on this thread; no shared execution thread.
                store.commit(event, position, engine, utc())
            else:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=.25)
                except asyncio.TimeoutError:
                    pass
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    args = parser.parse_args()
    # No stdout logging. Fatal storage/config errors go to a separate local file
    # and cause a nonzero process exit for the supervisor.
    try:
        asyncio.run(run(args))
    except Exception as exc:
        error_path = args.journal.with_suffix('.errors.jsonl')
        error_path.parent.mkdir(parents=True, exist_ok=True)
        with error_path.open('a') as f:
            f.write(dumps(dict(timestamp=utc().isoformat(), status='OBSERVER_STOPPED', error_type=type(exc).__name__))+'\n')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()

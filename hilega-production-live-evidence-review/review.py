"""Signed real-account observation continuity; no execution or ownership authority."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from market_lab.hilega_production_account_adapter_v1 import (
    AdapterBlocked, aware, canonical, day, identifier, intqty, positive_price, verify)

MODEL = 'HILEGA_LIVE_EVIDENCE_REVIEW_V1'
TERMINAL = {'FILLED', 'CANCELLED', 'REJECTED'}


def validate_rows(report):
    orders, trades, positions = {}, {}, {}
    for row in report['orders']:
        oid = identifier(row['order_id'])
        if oid in orders:
            raise AdapterBlocked('DUPLICATE_ORDER')
        identifier(row['instrument']); identifier(row['product'])
        q, f, p = (intqty(row[k]) for k in ('quantity', 'filled', 'pending'))
        if q <= 0 or f+p > q or row['side'] not in ('BUY', 'SELL'):
            raise AdapterBlocked('INVALID_ORDER')
        if row['status'] not in TERMINAL | {'OPEN', 'PARTIAL'}:
            raise AdapterBlocked('UNKNOWN_ORDER_STATUS')
        if row['status'] == 'FILLED' and (f != q or p):
            raise AdapterBlocked('INVALID_FILLED_ORDER')
        if row['status'] in {'CANCELLED', 'REJECTED'} and p:
            raise AdapterBlocked('INVALID_TERMINAL_ORDER')
        if row['status'] == 'REJECTED' and f:
            raise AdapterBlocked('REJECTED_ORDER_HAS_FILLS')
        at = aware(row['placed_at'])
        if day(at) != report['session_date'] or at > aware(report['completed_at']):
            raise AdapterBlocked('ORDER_TIME_INVALID')
        orders[oid] = row
    for row in report['trades']:
        key = (identifier(row['order_id']), identifier(row['trade_id']))
        if key in trades:
            raise AdapterBlocked('DUPLICATE_TRADE')
        order = orders.get(key[0])
        if not order or any(row[k] != order[k] for k in ('instrument', 'product', 'side')):
            raise AdapterBlocked('TRADE_IDENTITY_MISMATCH')
        if intqty(row['quantity']) <= 0:
            raise AdapterBlocked('INVALID_TRADE_QUANTITY')
        positive_price(row['price'])
        at = aware(row['filled_at'])
        if not aware(order['placed_at']) <= at <= aware(report['completed_at']):
            raise AdapterBlocked('TRADE_TIME_INVALID')
        trades[key] = row
    for oid, order in orders.items():
        if sum(t['quantity'] for k,t in trades.items() if k[0] == oid) != order['filled']:
            raise AdapterBlocked('ORDER_TRADE_FILL_TOTAL_MISMATCH')
    for row in report['positions']:
        key = (identifier(row['instrument']), identifier(row['product']))
        if key in positions:
            raise AdapterBlocked('DUPLICATE_POSITION')
        positions[key] = intqty(row['quantity'], signed=True)
    if report.get('account_position_rows_complete') is not True:
        raise AdapterBlocked('INCOMPLETE_POSITION_ROWS')
    return orders, trades, positions


def compare(previous, current):
    orders, trades, positions = validate_rows(current)
    if previous is None:
        return {'comparison': 'BASELINE_ONLY', 'changes': [], 'new_fill_count': 0}
    oldorders, oldtrades, oldpositions = validate_rows(previous)
    for oid, old in oldorders.items():
        new = orders.get(oid)
        if new is None:
            raise AdapterBlocked('PREVIOUS_ORDER_MISSING')
        if any(old[k] != new[k] for k in ('order_id','instrument','product','side','quantity','placed_at')):
            raise AdapterBlocked('ORDER_IDENTITY_CHANGED')
        if new['filled'] < old['filled']:
            raise AdapterBlocked('ORDER_FILL_REGRESSION')
        if old['status'] in TERMINAL and any(old[k] != new[k] for k in ('status','filled','pending')):
            raise AdapterBlocked('TERMINAL_ORDER_CHANGED')
    for key, old in oldtrades.items():
        if trades.get(key) != old:
            raise AdapterBlocked('PREVIOUS_FILL_MISSING_OR_CHANGED')
    newfills = [v for k,v in trades.items() if k not in oldtrades]
    changes = []
    for key in sorted(set(positions) | set(oldpositions) | {(v['instrument'],v['product']) for v in newfills}):
        before, after = oldpositions.get(key,0), positions.get(key,0)
        fills = [t for t in newfills if (t['instrument'],t['product']) == key]
        buys = sum(t['quantity'] for t in fills if t['side'] == 'BUY')
        sells = sum(t['quantity'] for t in fills if t['side'] == 'SELL')
        delta = after-before
        if delta != buys-sells:
            raise AdapterBlocked('POSITION_DELTA_NOT_EXPLAINED_BY_NEW_FILLS')
        if not fills and delta == 0:
            continue
        kind = 'ACCOUNT_ACTIVITY_UNATTRIBUTED'
        if before > 0 and 0 <= after < before and sells > 0 and buys == 0:
            kind = 'ACCOUNT_LONG_CLOSED_UNATTRIBUTED' if after == 0 else 'ACCOUNT_LONG_REDUCED_UNATTRIBUTED'
        changes.append(dict(instrument=key[0],product=key[1],before=before,after=after,
                            new_buy_quantity=buys,new_sell_quantity=sells,classification=kind,
                            strategy_ownership_verified=False))
    return dict(comparison='ACCOUNT_ACTIVITY' if changes else 'NO_OBSERVED_CHANGE',
                changes=changes,new_fill_count=len(newfills))


class Journal:
    """Dedicated review DB; never attach the application controller or allocation DB."""
    def __init__(self, directory, pin):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        marker = self.directory/'review-scope.json'
        expected = dict(model=MODEL,account_scope=pin['scope'])
        db = self.directory/'evidence.sqlite3'
        if marker.is_symlink() or db.is_symlink():
            raise AdapterBlocked('SYMLINK_REVIEW_FILES_REJECTED')
        if marker.exists():
            if json.loads(marker.read_text()) != expected:
                raise AdapterBlocked('REVIEW_SCOPE_MISMATCH')
        else:
            if any(self.directory.iterdir()):
                raise AdapterBlocked('NEW_EMPTY_REVIEW_DIRECTORY_REQUIRED')
            with marker.open('x') as f: json.dump(expected,f)
            marker.chmod(0o600)
        self.path, self.pin = db, pin
        with self.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY, digest TEXT NOT NULL, data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS review_state(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);')
        db.chmod(0o600)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path,timeout=10,isolation_level='DEFERRED')
        try:
            c.execute('PRAGMA synchronous=FULL')
            with c:
                yield c
        finally:
            c.close()

    def record(self, report, *, as_of):
        # Invalid input never replaces the accepted baseline. A failure result is
        # persisted separately, so a previous successful review is not current health.
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                verify(report,self.pin,as_of=as_of)
                validate_rows(report)
                sid = identifier(report['snapshot_id'])
                digest = hashlib.sha256(canonical(report)).hexdigest()
                duplicate = c.execute('SELECT digest FROM captures WHERE id=?',(sid,)).fetchone()
                if duplicate:
                    if duplicate[0] != digest: raise AdapterBlocked('SNAPSHOT_ID_CONFLICT')
                    raise AdapterBlocked('DUPLICATE_CAPTURE_NOT_NEW_EVIDENCE')
                last = c.execute('SELECT data FROM captures ORDER BY rowid DESC LIMIT 1').fetchone()
                previous = json.loads(last[0]) if last else None
                if previous:
                    if aware(report['generated_at']) <= aware(previous['completed_at']):
                        raise AdapterBlocked('CAPTURE_OVERLAP_OR_OUT_OF_ORDER')
                    if previous['session_date'] != report['session_date']:
                        # Overnight holdings/expiry require separate review; never infer a close.
                        raise AdapterBlocked('NEW_SESSION_REQUIRES_NEW_REVIEW_DIRECTORY')
                result = compare(previous,report)
                result.update(status='READ_ONLY_REVIEWED',reason=None,capture_verified=True,
                              snapshot_id=sid,generated_at=report['generated_at'],reviewed_at=as_of)
                c.execute('INSERT INTO captures VALUES(?,?,?)',(sid,digest,json.dumps(report,allow_nan=False)))
            except (AdapterBlocked,KeyError,TypeError,ValueError) as exc:
                reason = str(exc) if isinstance(exc,AdapterBlocked) else 'EVIDENCE_SCHEMA_INVALID'
                result = dict(status='REVIEW_REQUIRED',reason=reason,capture_verified=False,reviewed_at=as_of,
                              changes=[],new_fill_count=None,comparison='UNKNOWN')
            result.update(model=MODEL,entry_permission=False,production_execution_enabled=False,
                          orders_sent=False,application_ledger_updated=False,
                          strategy_ownership_verified=False,reservation_release_permission=False,
                          source_atomic=False)
            c.execute('INSERT OR REPLACE INTO review_state VALUES(1,?)',(json.dumps(result,allow_nan=False),))
            return result

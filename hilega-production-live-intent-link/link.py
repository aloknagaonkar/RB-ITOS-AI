"""Read-only durable BUY intent/receipt/capture chain assessment; no authority."""
import hashlib
import importlib.util
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from market_lab.hilega_production_account_adapter_v1 import (
    AdapterBlocked, aware, canonical, day, identifier, verify)

ROOT = Path(__file__).resolve().parent.parent
MODEL = 'HILEGA_LIVE_INTENT_LINK_ASSESSMENT_V1'


class Blocked(ValueError):
    pass


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, reason):
    if not condition:
        raise Blocked(reason)


def dependencies(root=ROOT):
    expected = json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for name, wanted in expected.items():
        path = root / name
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == wanted,
                'INSTALLED_DEPENDENCY_VERSION_MISMATCH')
    spec = importlib.util.spec_from_file_location(
        'hilega_intent_continuity', root/'hilega-production-live-evidence-review/review.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def readonly(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'REGULAR_SOURCE_DATABASE_REQUIRED')
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=10)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def source_capture(directory, pin, as_of, continuity):
    directory = Path(directory)
    marker = directory/'review-scope.json'
    require(marker.is_file() and not marker.is_symlink(), 'REVIEW_SCOPE_MARKER_REQUIRED')
    require(json.loads(marker.read_text()) == {
        'model': 'HILEGA_LIVE_EVIDENCE_REVIEW_V1', 'account_scope': pin['scope']},
        'REVIEW_SCOPE_MISMATCH')
    with readonly(directory/'evidence.sqlite3') as db:
        state = db.execute('SELECT data FROM review_state WHERE id=1').fetchone()
        captures = db.execute('SELECT id,digest,data FROM captures ORDER BY rowid').fetchall()
    require(state is not None and bool(captures), 'ACCEPTED_CAPTURE_REQUIRED')
    state = json.loads(state[0])
    require(state.get('status') == 'READ_ONLY_REVIEWED' and
            state.get('capture_verified') is True, 'LATEST_REVIEW_NOT_SUCCESSFUL')
    previous = None
    for sid, fingerprint, raw in captures:
        report = json.loads(raw)
        require(sid == report['snapshot_id'] and digest(report) == fingerprint,
                'CAPTURE_CONTENT_CHANGED')
        # Historical signatures checked at capture completion; latest checked NOW below.
        verify(report, pin, as_of=report['completed_at'])
        if previous:
            require(aware(report['generated_at']) > aware(previous['completed_at']) and
                    report['session_date'] == previous['session_date'],
                    'CAPTURE_HISTORY_NOT_CONTINUOUS')
        continuity.compare(previous, report)
        previous = report
    require(state.get('snapshot_id') == previous['snapshot_id'], 'LATEST_REVIEW_CAPTURE_MISMATCH')
    require(aware(previous['completed_at']) <= aware(state['reviewed_at']) <= aware(as_of),
            'REVIEW_TIME_INVALID')
    verify(previous, pin, as_of=as_of)
    return previous


def rows(db, table):
    # table names are fixed call-site constants, never CLI input.
    result = []
    for key, raw in db.execute('SELECT id,data FROM '+table):
        value = json.loads(raw)
        require(value.get('id') == key, 'SOURCE_ROW_ID_MISMATCH')
        result.append(value)
    return result


def unique(items, field):
    result = {}
    for item in items:
        key = identifier(item[field])
        require(key not in result, 'DUPLICATE_SOURCE_ID')
        result[key] = item
    return result


def project(controller_db, adapter_db, report, pin, continuity):
    require(Path(controller_db).resolve() != Path(adapter_db).resolve(), 'DISTINCT_SOURCE_DATABASES_REQUIRED')
    orders, trades, _ = continuity.validate_rows(report)
    # Each read transaction is coherent. These independent stores and the broker
    # endpoint sweep are NOT a cross-database/remote atomic snapshot.
    with readonly(controller_db) as controller, readonly(adapter_db) as adapter:
        meta = adapter.execute('SELECT data FROM meta WHERE id=1').fetchone()
        require(meta is not None and json.loads(meta[0]) == {
            'scope': pin['scope'], 'mode': 'LIVE_CLOSED'}, 'LIVE_PINNED_ADAPTER_STORE_REQUIRED')
        intents = unique(rows(controller, 'intents'), 'id')
        holds = unique(rows(controller, 'sim_allocation_reservations'), 'id')
        request_records = adapter.execute('SELECT id,fingerprint,data FROM requests ORDER BY rowid').fetchall()
        attempts = adapter.execute('SELECT id,request_id,operation,data FROM attempts').fetchall()
        receipts = dict(adapter.execute('SELECT id,data FROM receipts').fetchall())
    require(bool(request_records), 'NO_DURABLE_ADAPTER_INTENTS')
    links, seen_orders, seen_requests = [], set(), set()
    for request_id, fingerprint, raw in request_records:
        request = json.loads(raw)
        identifier(request_id)
        require(request_id not in seen_requests, 'DUPLICATE_REQUEST_ID')
        seen_requests.add(request_id)
        fields = ('request_id','draft','signal_id','signal_at','direction','reservation_reference')
        require(request_id == request['request_id'] and
                digest({k: request[k] for k in fields}) == fingerprint, 'REQUEST_FINGERPRINT_INVALID')
        draft = request['draft']; body = draft['body']
        require(draft.get('model') == 'HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1' and
                draft.get('request_id') == request_id and
                all(draft.get(k) is False for k in ('submission_enabled','entry_permission','orders_sent')),
                'EXACT_DISABLED_DRAFT_REQUIRED')
        require(digest(body) == draft['fingerprint'], 'BODY_FINGERPRINT_INVALID')
        require(body['transaction_type'] == 'BUY', 'BUY_LINK_ONLY_EXIT_ATTRIBUTION_PENDING')
        require(type(body['quantity']) is int and body['quantity'] > 0, 'INVALID_REQUEST_QUANTITY')
        require(request['direction'] in {'BULLISH','BEARISH'}, 'DIRECTION_REQUIRED')
        require(aware(request['signal_at']) <= aware(draft['created_at']) <= aware(report['completed_at']) and
                day(aware(request['signal_at'])) == day(aware(draft['created_at'])) == report['session_date'],
                'INTENT_SESSION_OR_TIME_MISMATCH')
        intent = intents.get(request_id); hold = holds.get(request['reservation_reference'])
        require(intent is not None and hold is not None and hold['id'] == request_id,
                'DURABLE_CONTROLLER_INTENT_AND_RESERVATION_REQUIRED')
        require(intent['side'] == 'BUY' and intent['signal_id'] == request['signal_id'] and
                intent['signal_at'] == request['signal_at'] and
                intent['instrument'] == hold['instrument'] == body['instrument_token'] and
                type(intent['quantity']) is int and type(hold['quantity']) is int and
                intent['quantity'] == hold['quantity'] == body['quantity'],
                'CONTROLLER_INTENT_RESERVATION_MISMATCH')
        require(type(hold['held_cents']) is int and hold['held_cents'] > 0,
                'HELD_RESERVATION_REQUIRED')
        matching = [r for r in attempts if r[1] == request_id and r[2] == 'PLACE']
        require(len(matching) == 1, 'DURABLE_PLACE_ATTEMPT_REQUIRED')
        aid, rid, operation, raw_attempt = matching[0]
        attempt = json.loads(raw_attempt)
        wire = dict(method='POST',host='api-hft.upstox.com',path='/v3/order/place',body=body)
        require(attempt['attempt_id'] == aid and attempt['request_id'] == rid and
                attempt['operation'] == operation and attempt['wire'] == wire and
                attempt.get('retry_allowed') is False, 'ATTEMPT_REQUEST_WIRE_MISMATCH')
        require((draft['documented_method'],draft['documented_host'],draft['documented_path']) ==
                ('POST','api-hft.upstox.com','/v3/order/place'), 'PLACE_ENDPOINT_MISMATCH')
        require(aid in receipts, 'DURABLE_PLACE_RECEIPT_REQUIRED_NO_ADOPTION')
        receipt = json.loads(receipts[aid])
        require(receipt.get('origin') == 'LOCAL_HTTP_TRANSPORT' and
                receipt.get('attempt_id') == aid and receipt.get('wire_fingerprint') == digest(wire),
                'LOCAL_TRANSPORT_RECEIPT_CHAIN_INVALID')
        ack = receipt.get('body', {}); data = ack.get('data', {})
        ids = data.get('order_ids') if isinstance(data, dict) else None
        require(type(receipt.get('http_status')) is int and receipt['http_status'] == 200 and
                ack.get('status') == 'success' and isinstance(ids,list) and len(ids) == 1,
                'ACK_UNKNOWN_OR_SPLIT_REQUIRES_REVIEW')
        oid = identifier(ids[0])
        require(request.get('order_id') == oid, 'PERSISTED_ACK_ORDER_BINDING_REQUIRED')
        require(oid not in seen_orders, 'ORDER_ID_ALREADY_BOUND')
        seen_orders.add(oid)
        order = orders.get(oid)
        require(order is not None, 'ACK_ORDER_MISSING_FROM_SIGNED_CAPTURE')
        require(all(order[k] == body[v] for k,v in (
            ('instrument','instrument_token'),('product','product'),('side','transaction_type'),
            ('quantity','quantity'))), 'ACK_ORDER_IDENTITY_MISMATCH')
        require(aware(order['placed_at']) >= aware(draft['created_at']), 'ORDER_PREDATES_DURABLE_INTENT')
        fills = [t for (order_id,_),t in trades.items() if order_id == oid]
        links.append(dict(request_id=request_id,order_id=oid,attempt_id=aid,
            request_fingerprint=fingerprint,receipt_fingerprint=digest(receipt),
            controller_intent_fingerprint=digest(intent),reservation_fingerprint=digest(hold),
            instrument=order['instrument'],product=order['product'],side=order['side'],
            order_status=order['status'],filled_quantity=order['filled'],pending_quantity=order['pending'],
            fill_ids=sorted(t['trade_id'] for t in fills),fill_count=len(fills),
            local_record_chain_consistent=True,broker_attested_transport_provenance=False))
    return links


def assess(controller_db, adapter_db, review_directory, pin, *, as_of, root=ROOT):
    base = dict(model=MODEL,assessed_at=as_of,production_execution_enabled=False,
        entry_permission=False,orders_sent=False,application_ledger_updated=False,
        strategy_ownership_verified=False,reservation_release_permission=False,
        real_funds_reservation_verified=False,source_atomic=False,
        external_exit_attribution_verified=False)
    try:
        continuity = dependencies(root)
        report = source_capture(review_directory,pin,as_of,continuity)
        source_paths = [Path(controller_db).resolve(),Path(adapter_db).resolve(),
                        (Path(review_directory)/'evidence.sqlite3').resolve()]
        require(len(set(source_paths)) == 3, 'DISTINCT_SOURCE_DATABASES_REQUIRED')
        links = project(controller_db,adapter_db,report,pin,continuity)
        return dict(base,status='LOCAL_CHAIN_CONSISTENT_AUTHORITY_NOT_GRANTED',reason=None,
                    snapshot_id=report['snapshot_id'],capture_fingerprint=digest(report),links=links)
    except (Blocked,AdapterBlocked,KeyError,TypeError,ValueError,OSError,sqlite3.Error) as exc:
        # Stable reason codes only; never echo SQL, paths, raw data or credentials.
        reason = str(exc) if isinstance(exc,(Blocked,AdapterBlocked)) else 'SOURCE_SCHEMA_OR_ACCESS_INVALID'
        return dict(base,status='BLOCKED',reason=reason,links=[])


class AssessmentJournal:
    """Dedicated audit projection. Never a controller, ownership or release ledger."""
    def __init__(self, directory, pin, session_date, *, source_paths):
        import os
        self.directory = Path(directory)
        target = self.directory.resolve()
        require(not self.directory.is_symlink(), 'SYMLINK_OUTPUT_REJECTED')
        for source in source_paths:
            source = Path(source).resolve()
            require(source.parent != target and not source.is_relative_to(target),
                    'OUTPUT_MUST_BE_SEPARATE_FROM_SOURCES')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        marker = self.directory/'intent-link-scope.json'
        self.path = self.directory/'assessment.sqlite3'
        require(not marker.is_symlink() and not self.path.is_symlink(), 'SYMLINK_OUTPUT_REJECTED')
        expected = dict(model=MODEL,account_scope=pin['scope'],session_date=session_date)
        if marker.exists():
            require(json.loads(marker.read_text()) == expected, 'OUTPUT_SCOPE_OR_SESSION_MISMATCH')
        else:
            require(not any(self.directory.iterdir()), 'NEW_EMPTY_OUTPUT_DIRECTORY_REQUIRED')
            fd = os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(expected,stream)
        fd = os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS bindings(
                request_id TEXT PRIMARY KEY,order_id TEXT UNIQUE NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assessments(seq INTEGER PRIMARY KEY,data TEXT NOT NULL);''')

    def record(self, result):
        with sqlite3.connect(self.path,timeout=10) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            candidates = []
            if result['status'] == 'LOCAL_CHAIN_CONSISTENT_AUTHORITY_NOT_GRANTED':
                for link in result['links']:
                    fixed = {k:link[k] for k in ('request_id','order_id','attempt_id',
                                                'request_fingerprint','receipt_fingerprint')}
                    old = db.execute('SELECT data FROM bindings WHERE request_id=?',
                                     (link['request_id'],)).fetchone()
                    other = db.execute('SELECT request_id FROM bindings WHERE order_id=?',
                                       (link['order_id'],)).fetchone()
                    if (old and json.loads(old[0]) != fixed) or (other and other[0] != link['request_id']):
                        result = dict(result,status='BLOCKED',reason='DURABLE_LINK_CONFLICT',links=[])
                        candidates = []
                        break
                    candidates.append(fixed)
                for fixed in candidates:
                    db.execute('INSERT OR IGNORE INTO bindings VALUES(?,?,?)',
                               (fixed['request_id'],fixed['order_id'],canonical(fixed).decode()))
            # A failed assessment is current failure, never an old successful projection.
            db.execute('INSERT INTO assessments(data) VALUES(?)',(canonical(result).decode(),))
        return result

"""Verified recent-session coverage shared by live bootstrap and offline replay.

Calendar scope is deliberately explicit. Unknown years fail closed. Recovery only
reads historical candles; it never constructs an order transport. Original cache
roots are read-only. The dedicated verified cache retains replaced corrupt bytes.
"""
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
UNDERLYING = 'NSE_INDEX|Nifty 50'
FRESH_ROOT = Path('data/historical-evidence/hilega-3m-warmup-verified-v1')
POLICY = 'BOUNDED_RECENT_20_EXPECTED_SESSIONS_2026_V2'
SPECIAL = date(2026, 11, 8)
HOLIDAYS = frozenset(date.fromisoformat('2026-' + d) for d in (
    '01-15', '01-26', '03-03', '03-26', '03-31', '04-03', '04-14',
    '05-01', '05-28', '06-26', '09-14', '10-02', '10-20', '11-10',
    '11-24', '12-25'))
CALENDAR_SOURCES = (
    'https://www.nseindia.com/resources/exchange-communication-holidays',
    'https://nsearchives.nseindia.com/content/circulars/CMTR76941.pdf')


def session_day(day):
    if day.year != 2026:
        raise ValueError('WARMUP_CALENDAR_YEAR_NOT_REVIEWED:' + str(day.year))
    return day == SPECIAL or (day.weekday() < 5 and day not in HOLIDAYS)


def required_sessions(target, count=20):
    if not session_day(target):
        raise ValueError('TARGET_NOT_REVIEWED_TRADING_SESSION:' + str(target))
    days = []
    cursor = target - timedelta(days=1)
    while len(days) < count:
        if session_day(cursor):
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def validate_rows(raw, day):
    if not isinstance(raw, list):
        raise ValueError('WARMUP_CANDLE_LIST_REQUIRED:' + str(day))
    out = []
    for row in raw:
        stamp = datetime.fromisoformat(row['timestamp'])
        if stamp.tzinfo is None:
            raise ValueError('WARMUP_TIMEZONE_REQUIRED:' + str(day))
        stamp = stamp.astimezone(IST)
        values = [row[k] for k in ('open', 'high', 'low', 'close')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError('WARMUP_INVALID_OHLC:' + str(day))
        o, h, l, c = values
        if h < max(o, l, c) or l > min(o, c):
            raise ValueError('WARMUP_INVALID_OHLC:' + str(day))
        volume = row.get('volume')
        if volume is not None and (isinstance(volume, bool)
                or not isinstance(volume, (int, float)) or not math.isfinite(volume)
                or volume < 0 or int(volume) != volume):
            raise ValueError('WARMUP_INVALID_VOLUME:' + str(day))
        out.append(dict(timestamp=stamp.isoformat(), open=float(o), high=float(h),
                        low=float(l), close=float(c), volume=volume))
    out.sort(key=lambda r: r['timestamp'])
    start = datetime.combine(day, time(14, 20) if day == SPECIAL else time(9, 15), tzinfo=IST)
    count = 70 if day == SPECIAL else 375
    expected = [(start + timedelta(minutes=i)).isoformat() for i in range(count)]
    if [r['timestamp'] for r in out] != expected:
        raise ValueError('WARMUP_SESSION_COVERAGE_INVALID:' + str(day))
    return out


def read_session(path, day):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('WARMUP_REGULAR_CACHE_REQUIRED:' + str(day))
    body = json.loads(path.read_text())
    if (not isinstance(body, dict) or body.get('session_date') != day.isoformat()
            or body.get('underlying') != UNDERLYING):
        raise ValueError('WARMUP_CACHE_IDENTITY_INVALID:' + str(day))
    return validate_rows(body.get('candles'), day)


def warmup_bars(raw, day):
    from .session import aggregate_exact_3m
    rows = validate_rows(raw, day)
    # Preserve the engine's existing 09:15 anchored grid. 14:20 belongs to
    # an incomplete leading bucket and is explicitly excluded, never padded.
    if day == SPECIAL:
        rows = rows[1:]
    objects = [SimpleNamespace(**{**r, 'timestamp': datetime.fromisoformat(r['timestamp'])}) for r in rows]
    return aggregate_exact_3m(objects, day)


def fetch_session(source, day):
    # Preserve acquisition evidence when the worker is wrapped for recording or
    # playback. Do not unwrap recording sources without recording the read.
    try:
        if hasattr(source, 'historical_candles'):
            items = source.historical_candles(UNDERLYING, day)
        elif hasattr(source, '_call') and hasattr(source, 'upstream'):
            items = source._call('warmup', {'date': day.isoformat()},
                lambda: source.upstream.historical_candles(UNDERLYING, day))
        elif hasattr(source, 'warmup_candles'):
            items = source.warmup_candles(day, FRESH_ROOT)
        else:
            raise ValueError('NO_HISTORICAL_CANDLE_SOURCE')
        rows = [dict(timestamp=x.timestamp.isoformat(), open=x.open, high=x.high,
                     low=x.low, close=x.close, volume=getattr(x, 'volume', None)) for x in items]
    except Exception as exc:
        raise ValueError('WARMUP_FETCH_FAILED:' + str(day) + ':' + type(exc).__name__) from None
    return validate_rows(rows, day)


def save_session(root, day, rows):
    root = Path(root)
    if root.is_symlink() or any(p.is_symlink() for p in root.absolute().parents):
        raise ValueError('WARMUP_REGULAR_CACHE_ROOT_REQUIRED')
    root.mkdir(parents=True, exist_ok=True)
    target = root / (day.isoformat() + '.json')
    body = dict(model='HILEGA_VERIFIED_WARMUP_V1', session_date=day.isoformat(),
                underlying=UNDERLYING, candles=validate_rows(rows, day),
                fetched_at=datetime.now(IST).isoformat(), calendar_policy=POLICY,
                special_session_policy='REGULAR_GRID_COMPLETE_BUCKETS_14:21_TO_15:29')
    raw = (json.dumps(body, indent=2, allow_nan=False) + '\n').encode()
    if target.exists():
        if target.is_symlink():
            raise ValueError('WARMUP_REGULAR_CACHE_REQUIRED:' + str(day))
        try:
            if read_session(target, day) == body['candles']:
                return target
        except (ValueError, KeyError, TypeError, OSError):
            pass
        old = target.read_bytes()
        archived = root / (target.name + '.previous-' + hashlib.sha256(old).hexdigest())
        if archived.exists():
            if archived.is_symlink() or archived.read_bytes() != old:
                raise ValueError('WARMUP_ARCHIVE_CONFLICT:' + str(day))
        else:
            with archived.open('xb') as f:
                f.write(old); f.flush(); os.fsync(f.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=root, delete=False) as f:
            temporary = Path(f.name); f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, target)
        fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


def load_warmup(index, target, *, source=None, fresh_root=FRESH_ROOT):
    index = dict(index)
    needed = required_sessions(target)
    recovered = []
    for day in needed:
        key = day.isoformat()
        try:
            if key not in index:
                raise ValueError('MISSING_CACHE')
            read_session(index[key], day)
        except (ValueError, KeyError, TypeError, OSError):
            if source is None:
                raise ValueError('RECENT_WARMUP_MISSING_OR_INVALID:' + key) from None
            index[key] = save_session(fresh_root, day, fetch_session(source, day))
            recovered.append(key)
    # The seed window is exactly the same 20 reviewed sessions whose coverage
    # was established above. Never scan or seed unrelated older cache files.
    warm = [(str(day), read_session(index[str(day)], day)) for day in needed]
    report = dict(policy=POLICY, required_recent_sessions=len(needed),
        expected_last_session=needed[-1].isoformat(), warmup_first=warm[0][0],
        warmup_last=warm[-1][0], recovered_sessions=recovered,
        seed_sessions=len(warm),
        older_cache_entries_not_used=sum(key < str(needed[0]) for key in index),
        recent_source_sha256={d.isoformat(): hashlib.sha256(Path(index[d.isoformat()]).read_bytes()).hexdigest() for d in needed},
        calendar_sources=list(CALENDAR_SOURCES), freshness_verified=True,
        special_session_policy='REGULAR_GRID_COMPLETE_BUCKETS_14:21_TO_15:29')
    if report['warmup_last'] != report['expected_last_session']:
        raise ValueError('WARMUP_UNEXPECTED_LAST_SESSION')
    return warm, report


def validate_supplied_warmup(warmup, target):
    warmup = list(warmup)
    days = [d for d, _ in warmup]
    if len(days) != len(set(days)) or any(d >= target.isoformat() for d in days):
        raise ValueError('WARMUP_DUPLICATE_OR_FUTURE_SESSION')
    expected = {d.isoformat() for d in required_sessions(target)}
    if not expected <= set(days):
        raise ValueError('RECENT_WARMUP_SESSIONS_MISSING:' + ','.join(sorted(expected - set(days))))
    if max(days) != max(expected):
        raise ValueError('WARMUP_UNEXPECTED_LAST_SESSION')
    return [(d, validate_rows(rows, date.fromisoformat(d)))
            for d, rows in sorted(warmup) if d in expected]

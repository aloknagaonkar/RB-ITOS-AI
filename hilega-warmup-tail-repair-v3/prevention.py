"""Patch only the operational cache writer; no service or strategy changes."""
import ast, hashlib, os, stat, tempfile
from pathlib import Path
TARGET='backend/market_lab/hilega_milega_historical_replay_v1.py'
WRITER='''def _write_cache(path: Path, underlying: str, session_date: date, candles: Sequence[HistoricalCandle]) -> None:
    import os
    import tempfile
    import math
    values = list(candles)
    operational = path.parent.name == "hilega-milega-underlying-cache-v1"
    if operational and not values and path.exists():
        raise ValueError("EMPTY_REFRESH_CANNOT_REPLACE_OPERATIONAL_CACHE")
    if operational and values:
        if underlying != UNDERLYING or session_date >= datetime.now(IST).date():
            raise ValueError("COMPLETED_OPERATIONAL_SESSION_REQUIRED")
        expected = {datetime.combine(session_date, time(9, 15), tzinfo=IST) + timedelta(minutes=i) for i in range(375)}
        seen = set()
        for candle in values:
            stamp = candle.timestamp
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("AWARE_WARMUP_TIMESTAMP_REQUIRED")
            stamp = stamp.astimezone(IST)
            if stamp not in expected or stamp in seen:
                raise ValueError("EXACT_UNIQUE_WARMUP_MINUTES_REQUIRED")
            seen.add(stamp)
            o, h, l, c = candle.open, candle.high, candle.low, candle.close
            if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (o, h, l, c)) or not l <= min(o, c) <= max(o, c) <= h:
                raise ValueError("VALID_WARMUP_OHLC_REQUIRED")
        if seen != expected or len(aggregate_exact_5m(values, session_date, require_full_session=True)) != 75:
            raise ValueError("COMPLETE_375_MINUTE_WARMUP_REQUIRED")
    payload = {"schema_version": CACHE_SCHEMA_VERSION, "underlying": underlying, "session_date": session_date.isoformat(), "candles": [{"timestamp": c.timestamp.isoformat(), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume, "open_interest": c.open_interest} for c in values]}
    data = (json.dumps(payload, indent=2, allow_nan=False) + "\\n").encode()
    if any(p.is_symlink() for p in (path, *path.absolute().parents)):
        raise ValueError("REGULAR_WARMUP_CACHE_PATH_REQUIRED")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise ValueError("REGULAR_WARMUP_CACHE_REQUIRED")
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".complete-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
'''
def proposed(source):
    tree=ast.parse(source);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_write_cache']
    if len(nodes)!=1:raise ValueError('EXACT_CACHE_WRITER_REQUIRED')
    node=nodes[0];lines=source.splitlines(keepends=True)
    result=''.join(lines[:node.lineno-1])+WRITER+'\n'+''.join(lines[node.end_lineno:])
    old=ast.parse(source);new=ast.parse(result)
    for t in (old,new):t.body=[n for n in t.body if not(isinstance(n,ast.FunctionDef) and n.name=='_write_cache')]
    if ast.dump(old)!=ast.dump(new):raise ValueError('UNRELATED_SOURCE_CHANGE_BLOCKED')
    compile(result,TARGET,'exec');return result.encode()
def install(path,expected,desired,backup):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()==hashlib.sha256(desired).hexdigest():return False
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('CACHE_WRITER_SOURCE_CHANGED')
    fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    fd,name=tempfile.mkstemp(prefix='.warmup-writer-',dir=path.parent)
    try:
        os.fchmod(fd,stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(fd,'wb') as f:f.write(desired);f.flush();os.fsync(f.fileno())
        if path.read_bytes()!=raw:raise ValueError('CACHE_WRITER_CONCURRENT_CHANGE')
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
    return True

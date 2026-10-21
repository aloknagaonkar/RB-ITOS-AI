"""Content-addressed offline parity cache. Never imports saved executable data."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

SCHEMA = 'HILEGA_CONTROL_PARITY_CACHE_V1'
def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def fingerprint(day, raw, warm, source_paths, version):
    sources = {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
               for p in sorted(source_paths, key=str)}
    return digest(dict(schema=SCHEMA, day=day, raw=raw,
                       warm=[(d,r) for d,r in warm if d<day], sources=sources,
                       strategy_version=version, python=sys.version))

def load_or_validate(cache_root, key, build, validate, force=False):
    path=Path(cache_root)/(key+'.json')
    if not force:
        try:
            envelope=json.loads(path.read_text())
            payload=envelope['payload']
            if (envelope['sha256']==digest(payload) and payload['key']==key
                    and payload['schema']==SCHEMA and payload['parity']=='PASS'):
                return payload['baseline'], 'CACHED_PASS'
        except (OSError,ValueError,KeyError,TypeError):
            pass
    baseline=build()
    validate(baseline)  # Failures never write a PASS.
    payload=dict(schema=SCHEMA,key=key,parity='PASS',baseline=baseline)
    encoded=json.dumps(dict(payload=payload,sha256=digest(payload)),allow_nan=False)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as handle:
            temp=Path(handle.name);handle.write(encoded)
        os.replace(temp,path)
    finally:
        if temp is not None:temp.unlink(missing_ok=True)
    return baseline, 'FRESH_PASS'

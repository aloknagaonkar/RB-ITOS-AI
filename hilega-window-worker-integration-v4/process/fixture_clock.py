"""Explicit deterministic market clock, usable only in a marked disposable workspace."""
from datetime import datetime,timedelta
import json,time
from pathlib import Path
from window import need

def now(workspace):
    workspace=Path(workspace).resolve()
    marker=json.loads((workspace/'DISPOSABLE-WINDOW.json').read_text())
    need(marker==dict(model='HILEGA_DISPOSABLE_WINDOW_V1',workspace=str(workspace)),'DISPOSABLE_CLOCK_MARKER_REQUIRED')
    info=json.loads((workspace/'FIXTURE-CLOCK.json').read_text())
    elapsed=time.time()-info['wall_started']
    need(0<=elapsed<=600,'DISPOSABLE_CLOCK_EXPIRED_OR_REWOUND')
    rate=info.get('rate',1)
    need(rate in (0,1),'FIXTURE_CLOCK_RATE_INVALID')
    return datetime.fromisoformat(info['market_started'])+timedelta(seconds=elapsed*rate)

"""Read-only presentation of independently recorded shadow evaluations.

No broker, selector, worker or network imports. Frames are self-contained; the
collector must carry frozen entry identities forward rather than re-rank them.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

MODEL = 'HILEGA_STRIKE_OBSERVATION_FRAME_V1'
JOURNAL = Path(__file__).resolve().parents[2] / 'data/live-observation/hilega-strike-observation-v1/shadow_strike_obs.jsonl'


def reject_constant(value):
    raise ValueError('NONFINITE_JSON_NUMBER')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def project(frame, now):
    if frame.get('model') != MODEL:
        raise ValueError('UNSUPPORTED_FRAME_MODEL')
    rows = frame.get('top5', [])
    if not isinstance(rows, list) or len(rows) > 5:
        raise ValueError('INVALID_TOP5')
    keys = [r.get('instrument_key') for r in rows]
    if any(not k for k in keys) or len(keys) != len(set(keys)):
        raise ValueError('INVALID_SELECTED_IDENTITIES')
    result = dict(frame)
    result['top5'] = []
    for rank, source in enumerate(rows, 1):
        row = dict(source, rank=rank, points=None, pnl_rupees=None, roi_percent=None)
        row['pnl_status'] = 'PRICE_EVIDENCE_UNAVAILABLE'
        entry, qty, costs = (source.get(k) for k in ('entry_ask', 'quantity', 'total_cost_rupees'))
        closed = source.get('state') == 'CLOSED'
        price = source.get('exit_bid' if closed else 'current_bid')
        stamp = source.get('exit_quote_timestamp' if closed else 'quote_timestamp')
        max_age = frame.get('max_quote_age_seconds')
        try:
            quote = datetime.fromisoformat(stamp)
            if quote.tzinfo is None:
                raise ValueError('UNZONED_QUOTE')
            age = (now - quote).total_seconds()
            fresh = age >= 0 and (closed or (number(max_age) and 0 < max_age and age <= max_age))
        except (ValueError, TypeError):
            fresh = False
        evidence = source.get('price_evidence_source') in ('MARKET_UPDATE', 'RECORDED_FEED_UPDATE')
        valid = all(number(v) for v in (entry, qty, costs, price)) and entry > 0 and qty > 0 and float(qty).is_integer() and costs >= 0 and price >= 0
        if valid and fresh and evidence:
            row['points'] = price - entry
            row['pnl_rupees'] = (price - entry) * qty - costs
            row['roi_percent'] = row['pnl_rupees'] / (entry * qty) * 100
            row['pnl_status'] = 'CLOSED_HYPOTHETICAL' if closed else 'OPEN_HYPOTHETICAL'
        elif valid:
            row['pnl_status'] = 'STALE_OR_UNVERIFIED_QUOTE'
        result['top5'].append(row)
    return result


def dashboard(path=JOURNAL, now=None):
    now = now or datetime.now(timezone.utc)
    output = dict(status='NOT_CONNECTED', observation_only=True, frames=[], errors=[], read_at=now.isoformat())
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            offset = max(0, size - 2 * 1024 * 1024)
            stream.seek(offset)
            if offset:
                stream.readline()  # discard a potentially truncated first record
            lines = stream.read().splitlines(keepends=True)
    except FileNotFoundError:
        return output
    except OSError:
        output['status'] = 'READ_ERROR'
        output['errors'] = ['OBSERVATION_JOURNAL_UNREADABLE']
        return output
    for line in lines[-50:]:
        if not line.endswith(b'\n'):
            continue  # writer may still be appending this frame
        try:
            frame = json.loads(line, parse_constant=reject_constant)
            output['frames'].append(project(frame, now))
        except (ValueError, TypeError, AttributeError, KeyError):
            output['errors'].append('INVALID_OBSERVATION_FRAME')
    output['frames'].reverse()
    output['status'] = 'RECORDED_OBSERVATIONS' if output['frames'] else 'WAITING_FOR_DATA'
    return output

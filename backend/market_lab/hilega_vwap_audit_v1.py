"""Read-only VWAP inspection. Reconstructed evidence is never labelled live."""
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT/'data/live-observation/hilega-vwap-signal-v1/signal-vwap-observations.jsonl'
REPORT = ROOT/'data/research/hilega-vwap-oct13-14/report.json'
IST = ZoneInfo('Asia/Kolkata')
LIMIT = 16*1024*1024


def instant(value):
    at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return at


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def cached_checkpoint(target, folders, issues):
    """Only complete, contiguous candles available by the requested checkpoint.

    This uses saved files and makes no HTTP requests. A later download can
    reconstruct an earlier checkpoint, but cannot prove capture at that time.
    """
    from hilega_vwap_signal_review.collect import vwap_at
    at = target.astimezone(IST)
    day = at.date().isoformat()
    for folder in dict.fromkeys(folders):
        manifest = folder/f'{day}-futures-contract.json'
        candles_path = folder/f'{day}-futures-ohlcv.json'
        if not manifest.exists() or not candles_path.exists():
            continue
        try:
            if manifest.stat().st_size > LIMIT or candles_path.stat().st_size > LIMIT:
                raise ValueError('SAVED_FUTURES_SIZE_LIMIT')
            contract = json.loads(manifest.read_text())
            if contract.get('underlying_key') != 'NSE_INDEX|Nifty 50' or not contract.get('instrument_key'):
                raise ValueError('INVALID_SAVED_FUTURES_CONTRACT')
            if str(contract.get('expiry', '')) < day:
                raise ValueError('SAVED_FUTURES_CONTRACT_EXPIRED')
            body = json.loads(candles_path.read_text())
            values = vwap_at(body['data']['candles'], at)
            return dict(values, signal_time=target.isoformat(), session_date=day,
                        kind='DECISION_CHECKPOINT', direction='NONE', source='SAVED_FUTURES_CANDLES',
                        instrument_key=contract['instrument_key'], status='AVAILABLE',
                        evidence_type='RECONSTRUCTED_FROM_SAVED_CANDLES',
                        reconstructed=True, saved_candles_path=str(candles_path))
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isupper() else 'INVALID_SAVED_FUTURES_DATA'
            issues.append(reason)
    return None


def inspect(at, live=LIVE, report=REPORT):
    target = instant(at)
    result = dict(status='NOT_RECORDED', observation_only=True, entry_filter_enabled=False,
                  decision_timestamp=target.isoformat(), rows=[], issues=[])
    candidates = []
    try:
        if live.exists():
            with live.open('rb') as stream:
                stream.seek(0, 2)
                offset = max(0, stream.tell()-4*1024*1024)
                stream.seek(offset)
                if offset:
                    stream.readline()
                    result['issues'].append('JOURNAL_WINDOW_TRUNCATED')
                for line in stream.read().splitlines(keepends=True):
                    if not line.endswith(b'\n'):
                        continue  # Collector may currently be appending this record.
                    try:
                        candidates.append((json.loads(line), 'OBSERVATION_JOURNAL'))
                    except (ValueError, UnicodeError):
                        result['issues'].append('INVALID_JOURNAL_RECORD')
    except OSError:
        result['issues'].append('VWAP_JOURNAL_READ_ERROR')
    # Also inspect the managed collector's latest report, including failure reasons.
    for path in dict.fromkeys((live.parent/'report.json', report)):
        try:
            if path.exists():
                if path.stat().st_size > LIMIT:
                    result['issues'].append('RESEARCH_REPORT_SIZE_LIMIT')
                else:
                    origin = 'COLLECTOR_REPORT' if path == live.parent/'report.json' else 'RECONSTRUCTED_RESEARCH_REPORT'
                    candidates.extend((row, origin) for row in json.loads(path.read_text()).get('rows', []))
        except (OSError, ValueError, TypeError, AttributeError):
            result['issues'].append('VWAP_REPORT_READ_ERROR')

    def append_valid(source, origin, seen):
        try:
            if instant(source.get('signal_time')) != target:
                return
            identity = (source['kind'], source['direction'], source['source'])
            if identity in seen:
                return
            if source.get('status') != 'AVAILABLE':
                result['issues'].append(source.get('reason', 'VWAP_UNAVAILABLE'))
                return
            if source.get('basis') != 'NIFTY_FUTURES_SESSION_5M_TYPICAL_PRICE_PROXY':
                raise ValueError('UNSUPPORTED_VWAP_BASIS')
            if source['kind'] not in ('SETUP', 'CONFIRMED_ENTRY', 'DECISION_CHECKPOINT', 'ARMED_CANDIDATE'):
                raise ValueError('INVALID_OBSERVATION_IDENTITY')
            if source['direction'] not in ('BULLISH', 'BEARISH', 'NONE') or (source['direction'] == 'NONE' and source['kind'] != 'DECISION_CHECKPOINT'):
                raise ValueError('INVALID_OBSERVATION_IDENTITY')
            if source['kind'] == 'ARMED_CANDIDATE':
                flag = 'bullish_armed' if source['direction'] == 'BULLISH' else 'bearish_armed'
                if (source.get('context_evidence') or {}).get(flag) is not True:
                    raise ValueError('CANDIDATE_ARM_EVIDENCE_REQUIRED')
            if not all(finite(source.get(key)) for key in ('vwap', 'futures_close', 'distance_points')) or min(source['vwap'], source['futures_close']) <= 0:
                raise ValueError('INVALID_VWAP_NUMBERS')
            available = instant(source['candle_available_at'])
            age = (target-available).total_seconds()
            if available.astimezone(IST).date() != target.astimezone(IST).date() or not 0 <= age < 300:
                raise ValueError('NONCAUSAL_OR_STALE_VWAP_CANDLE')
            distance = source['futures_close']-source['vwap']
            if abs(distance-source['distance_points']) > 1e-6:
                raise ValueError('VWAP_DISTANCE_MISMATCH')
            position = 'ABOVE' if distance > 0 else 'BELOW' if distance < 0 else 'AT'
            agreement = position == ('ABOVE' if source['direction'] == 'BULLISH' else 'BELOW') if source['direction'] != 'NONE' else None
            result['rows'].append(dict(source, origin=origin, price_position=position,
                                       direction_agrees_with_vwap=agreement, age_at_signal_seconds=age))
            seen.add(identity)
        except (ValueError, TypeError, KeyError, AttributeError):
            result['issues'].append('INVALID_OR_NONCAUSAL_VWAP_RECORD')

    seen = set()
    for source, origin in candidates:
        append_valid(source, origin, seen)
    if any(row['kind'] == 'ARMED_CANDIDATE' for row in result['rows']):
        # Older neutral rows remain immutable in the journal. Suppress only
        # their obsolete presentation when exact armed-context evidence exists.
        neutral = [row for row in result['rows'] if row['kind'] == 'DECISION_CHECKPOINT' and row['direction'] == 'NONE']
        result['superseded_context_rows'] = len(neutral)
        result['rows'] = [row for row in result['rows'] if row not in neutral]
    if not result['rows']:
        reconstructed = cached_checkpoint(target, [live.parent, report.parent], result['issues'])
        if reconstructed:
            append_valid(reconstructed, 'RECONSTRUCTED_FROM_SAVED_FUTURES', seen)
    if result['rows']:
        result['status'] = 'AVAILABLE'
    result['issues'] = list(dict.fromkeys(str(issue) for issue in result['issues']))
    return result

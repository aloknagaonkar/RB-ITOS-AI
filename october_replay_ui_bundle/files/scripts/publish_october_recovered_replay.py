"""Recompute recovered UI artifacts offline using installed engines, never broker APIs."""
import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from market_lab.hilega_milega_historical_replay_v1 import _read_cache, aggregate_exact_5m, UNDERLYING
from market_lab.hilega_milega_strategy_v1 import HilegaMilegaIndicatorEngineV1
from market_lab.hilega_directional_coordinator_v1 import HilegaDirectionalCoordinatorV1
from market_lab.hilega_wma_gap_historical_v1 import build_v1_session, build_wma_gap_session, _report, _step
from market_lab.recovered_replay_ui_v1 import ROOT, LABEL
from scripts.research_hilega_alignment_points_490 import replay
from scripts.backtest_hilega_wma_gap_490 import simulate, write_csv
from market_lab.midpoint_strategy.config import live_shadow_config_from_env
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1

DAYS = ['2026-10-06', '2026-10-07']
INPUT = Path('data/recovery/october-2026/replay-input')

class OfflineSources:
    def __getattr__(self, name):
        raise RuntimeError('External data access prohibited in recovered replay: ' + name)

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str))

def publish():
    if ROOT.exists():
        raise RuntimeError('Recovery UI artifacts already exist; preserve them before rebuilding')
    # Work outside live/frozen directories. Publish only after all engines succeed.
    with tempfile.TemporaryDirectory(prefix='october-replay-') as tmp:
        stage = Path(tmp) / 'ui'; cache = INPUT / 'replay-warmup'
        sessions = sorted(p.stem for p in cache.glob('*.json'))
        if not all((cache / (day + '.json')).exists() for day in DAYS):
            raise ValueError('Recovered exact minute caches are missing')
        engine = HilegaMilegaIndicatorEngineV1(); coordinator = HilegaDirectionalCoordinatorV1()
        features = {}; history = []; candle_reports = {day: [] for day in DAYS}
        for day in sessions:
            candles = _read_cache(cache / (day + '.json'), UNDERLYING, date.fromisoformat(day))
            if not candles:
                continue
            bars = aggregate_exact_5m(candles, date.fromisoformat(day), require_full_session=True)
            if len(bars) != 75:
                raise ValueError('Incomplete exact session: ' + day)
            for bar in bars:
                snapshot = engine.update(float(bar.close)); feature = asdict(snapshot)
                feature['ema_minus_wma'] = snapshot.ema3_rsi - snapshot.wma21_rsi if snapshot.ready else None
                for field in ('rsi9', 'ema3_rsi', 'wma21_rsi', 'ema_minus_wma'):
                    feature[field + '_slope_3'] = (feature[field] - history[-3][field]) / 3 if len(history) >= 3 and feature[field] is not None and history[-3][field] is not None else None
                features[(day, bar.ts.strftime('%H:%M'))] = feature; history.append(feature)
                decision = coordinator.on_bar(bar)
                if day not in DAYS:
                    continue
                raw = asdict(decision)
                events = [asdict(e) for e in decision.accepted_events]
                direction = str(decision.trade_owner_after)
                if direction == 'NONE':
                    direction = str(decision.trade_owner_before)
                steps = [_step('Canonical ' + key, 'INFO', value, 'Installed canonical engine', 'Reconstructed from exact historical candles; not recorded live.') for key, value in raw.items() if key not in ('accepted_events', 'suppressed_events')]
                steps += [_step(key, 'INFO', value, 'Indicator evidence', 'Five-minute completed candle value.') for key, value in feature.items()]
                row = _report(bar.ts.isoformat(), {'direction': direction, 'entry_timestamp': bar.ts.isoformat()}, event='CANONICAL_CANDLE_DECISION', state_before=str(decision.trade_owner_before), state_after=str(decision.trade_owner_after), close=float(bar.close), steps=steps)
                row['bar'] = {'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close, 'volume': bar.volume}
                row['indicators'] = feature
                previous = history[-2] if len(history) >= 2 else {}
                row['indicators'].update({'previous_' + key: previous.get(key) for key in ('rsi9', 'ema3_rsi', 'wma21_rsi')})
                row['conditions']['strategy_steps'].append(_step('EMA3–WMA21 gap comparison', 'INFO',
                    {'previous_gap': previous.get('ema_minus_wma'), 'current_gap': feature.get('ema_minus_wma')},
                    'Diagnostic only — canonical V1 is unchanged', 'Gap uses EMA3(RSI9) minus WMA21(RSI9).'))
                row['conditions']['canonical_decision'] = raw
                row['transitions'] = events
                row['strategy'].update({'strategy_id': 'HILEGA_V1_REPLAY', 'events_emitted': [e.event_type for e in decision.accepted_events], 'accepted': bool(events), 'bullish_state': decision.bullish_state, 'bearish_state': decision.bearish_state})
                row['audit_integrity'] = {'source': LABEL, 'recorded_live': False, 'chain_ok': None}
                candle_reports[day].append(row)
        trades, _ = replay(cache_root=cache, all_sessions=sessions, analysis_sessions=DAYS, feature_lookup=features, flat_epsilon=.1)
        trace = []
        results, attempts, unavailable = simulate(trades=trades, cache_root=cache, threshold=.75, strong_threshold=1, timeout_minutes=10, timeline_out=trace)
        if unavailable:
            raise ValueError('Unavailable exact indicator evidence: ' + str(unavailable))
        research = Path(tmp) / 'research'; research.mkdir()
        write_csv(research / 'trade-results.csv', results)
        write_csv(research / 'confirmation-attempts.csv', attempts)
        write_csv(research / 'candidate-timeline.csv', trace)
        for day in DAYS:
            for name, builder in [('v1', build_v1_session), ('v2', build_wma_gap_session)]:
                payload = builder(day, research)
                if name == 'v1':
                    payload['reports'] = candle_reports[day]; payload['report_count'] = len(candle_reports[day])
                payload.update({'source': LABEL, 'source_id': 'recovered:' + day, 'evidence_cohort': LABEL, 'forward_confirmation_eligible': False, 'observation_only': True, 'execution_enabled': False,
                    'warning': 'Recovered Historical Replay — reconstructed market data, not recorded live or untouched forward confirmation. Times are candle labels, not broker fills; option P&L and fees excluded.'})
                payload['recovered_trades'] = [r for r in results if r['session_date'] == day]
                payload['performance_summary'][0] = {'strategy_id': 'LIVE_RECORDED_V1', 'available': False, 'reason': 'No supplied recorded-live audit for this date', 'signals': None, 'entries': None, 'net_points': None}
                for row in payload['reports']:
                    row.setdefault('audit_integrity', {}).update({'source': LABEL, 'recorded_live': False})
                dump(stage / 'hilega' / day / (name + '.json'), payload)
        config = live_shadow_config_from_env()
        # Disable external research collectors only; strategy config remains the installed env config.
        old = os.environ.get('MIDPOINT_V62_OOS_COLLECTOR_ENABLED')
        os.environ['MIDPOINT_V62_OOS_COLLECTOR_ENABLED'] = '0'
        manifest = {'model': 'RECOVERED_MIDPOINT_UI_V1', 'sessions': []}
        try:
            for day in DAYS:
                out = stage / 'midpoint' / day; out.mkdir(parents=True)
                minutes = INPUT / 'midpoint' / day / 'minutes.jsonl'
                rows = [json.loads(line) for line in minutes.read_text().splitlines() if line.strip()]
                if len(rows) != 360:
                    raise ValueError('Midpoint needs exact 360 minute rows: ' + day)
                coord = MidpointLiveShadowCoordinatorV1(market_sources=OfflineSources(), audit_path=out / 'audit.jsonl', config=config)
                coord._reset_session(date.fromisoformat(day))
                candles = {datetime.fromisoformat(r['timestamp']): SimpleNamespace(timestamp=datetime.fromisoformat(r['timestamp']), open=r['underlying_open'], high=r['underlying_high'], low=r['underlying_low'], close=r['underlying_close'], volume=0) for r in rows}
                for r in rows:
                    stamp = datetime.fromisoformat(r['timestamp'])
                    coord._process_minute(ts=stamp, underlying=candles[stamp], futures_close=r['futures_close'], futures_vwap=r['futures_vwap'], futures_open=r.get('futures_open'), futures_volume=r['futures_volume'], underlying_by_ts={t: c for t, c in candles.items() if t <= stamp})
                if not (out / 'audit.jsonl').exists():
                    (out / 'audit.jsonl').touch()
                shutil.copy2(minutes, out / 'minutes.jsonl')
                manifest['sessions'].append({'session_date': day, 'minute_count': len(rows), 'event_count': len((out / 'audit.jsonl').read_text().splitlines()), 'block': LABEL, 'source': LABEL,
                    'configuration': asdict(config), 'warning': 'Recovered replay, not live evidence. Missing futures_open means some health evidence is unavailable.'})
        finally:
            if old is None:
                os.environ.pop('MIDPOINT_V62_OOS_COLLECTOR_ENABLED', None)
            else:
                os.environ['MIDPOINT_V62_OOS_COLLECTOR_ENABLED'] = old
        dump(stage / 'midpoint' / 'manifest.json', manifest)
        ROOT.parent.mkdir(parents=True, exist_ok=True)
        pending = ROOT.with_name(ROOT.name + '.pending')
        if pending.exists():
            raise RuntimeError('Pending recovery publication exists; inspect before retrying')
        shutil.copytree(stage, pending)
        pending.rename(ROOT)
    print(json.dumps({'status': 'PUBLISHED_RECOVERED_REPLAY', 'dates': DAYS, 'root': str(ROOT), 'recorded_live': False, 'execution_enabled': False}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', required=True, choices=['PUBLISH_RECOVERED_REPLAY_ONLY'])
    parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv('.env', override=False)
    publish()

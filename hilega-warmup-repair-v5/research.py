"""VM-only candle recovery and fresh replay. No audit or position writes."""
import argparse
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from dotenv import load_dotenv


def partial_replay(e, day, raw, warmup, through):
    from market_lab.hilega_three_minute_v1.warmup import validate_supplied_warmup, warmup_bars
    from market_lab.hilega_three_minute_v1.session import aggregate_exact_3m
    from market_lab.domain import IST
    warmup = validate_supplied_warmup(warmup, day)
    if through >= datetime.combine(day, time(15, 30), tzinfo=IST):
        full = e.replay(day.isoformat(), raw, warmup)
        return dict(session_date=day.isoformat(), strategy_version=e.VERSION,
            through=through.isoformat(), trades=full['trades'], open_trade=None,
            decisions=full['audit'], closed_points=sum(t['points'] for t in full['trades']),
            execution_enabled=False, scope='ISOLATED_RESEARCH_WITH_REFRESHED_WARMUP')
    canonical = e.ExitFirstCanonical(); tracker = e.PriceFrames(); gate = e.make_gate(tracker.frames)
    for d, rows in warmup:
        for bar in warmup_bars(rows, date.fromisoformat(d)):
            canonical.on_bar(bar); tracker.seed(bar)
    reference = e.capture_opening_reference(canonical, day)
    canonical.bullish.session = e.SessionState(session_date=day)
    canonical.bearish.session = e.BearishSessionState(session_date=day)
    for engine in (canonical.bullish, canonical.bearish):
        engine.previous_indicators = None; engine.previous_bar = None
    canonical.trade_owner = 'NONE'; canonical.session_date = day
    start = datetime.combine(day, time(9, 15), tzinfo=IST)
    minutes = int((through - start).total_seconds() // 60)
    rows = [r for r in e.candles(raw) if start <= r.timestamp < through]
    if [r.timestamp for r in rows] != [start + timedelta(minutes=i) for i in range(minutes)]:
        raise ValueError('RESEARCH_CURRENT_SESSION_MINUTES_MISSING_OR_DUPLICATED')
    count = len(rows) // 3 * 3
    if not count:
        raise ValueError('RESEARCH_NO_COMPLETED_3M_CANDLE')
    trades = []; active = None; decisions = []
    for bar in aggregate_exact_3m(rows[:count], day):
        at = bar.ts + timedelta(minutes=3)
        ref = e.confirmation_reference(canonical.bullish.previous_indicators, reference, at-timedelta(minutes=1))
        result = e.advance_boundary(canonical, gate, bar, ref, tracker)
        decisions.append(dict(time=at.isoformat(), close=bar.close, frame=result['frame'],
            owner=gate.owner, checks=result['checks'], policy_events=result['policy_events']))
        for event in result['exits']:
            if active is None:
                raise ValueError('RESEARCH_EXIT_WITHOUT_ENTRY')
            active.update(exit_time=at.isoformat(), exit_price=event.price,
                          points=event.points, exit_reason=event.exit_reason or event.event_type)
            trades.append(active); active = None
        for event in result['entries']:
            if active is not None:
                raise ValueError('RESEARCH_ENTRY_BEFORE_EXIT')
            active = dict(direction=e.direction(event), entry_time=at.isoformat(),
                entry_price=event.price, entry_checks=event.details['wma_gap'])
    for trade in trades + ([active] if active else []):
        sign = 1 if trade['direction'] == 'BULLISH' else -1
        entry = datetime.fromisoformat(trade['entry_time'])
        end = datetime.fromisoformat(trade['exit_time']) if trade.get('exit_time') else through
        held = [r for r in rows if entry <= r.timestamp < end]
        peak = max([0.] + [sign*((r.high if sign == 1 else r.low)-trade['entry_price']) for r in held])
        points = trade.get('points')
        if points is None:
            points = sign*(rows[-1].close-trade['entry_price'])
            trade.update(current_points=points, mark_time=(rows[-1].timestamp+timedelta(minutes=1)).isoformat())
        trade.update(mfe_points=peak, giveback_points=peak-points)
    return dict(session_date=day.isoformat(), strategy_version=e.VERSION, through=through.isoformat(),
        trades=trades, open_trade=active, decisions=decisions,
        closed_points=sum(t['points'] for t in trades), execution_enabled=False,
        scope='ISOLATED_RESEARCH_WITH_REFRESHED_WARMUP')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--day', required=True)
    args = p.parse_args()
    from market_lab.domain import IST
    from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
    from market_lab.hilega_three_minute_v1 import hilega_combined_replay_v1 as e
    from market_lab.hilega_three_minute_v1.warmup import load_warmup
    load_dotenv(args.repo/'.env')
    now = datetime.now(IST); day = date.fromisoformat(args.day)
    if day != now.date():
        raise ValueError('PREPARATION_MUST_TARGET_TODAY')
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.output/'verified-candles'
    index = e.cache_index()
    for path in sorted(root.glob('????-??-??.json')):
        index[path.stem] = path
    source = UpstoxLiveShadowSourcesV1(os.getenv('UPSTOX_ACCESS_TOKEN', ''))
    print('Recovering and validating the 20 expected prior sessions...', flush=True)
    warm, coverage = load_warmup(index, day, source=source, fresh_root=root)
    print(json.dumps(coverage, indent=2), flush=True)
    def rows(items):
        return [dict(timestamp=c.timestamp.isoformat(), open=c.open, high=c.high,
                     low=c.low, close=c.close, volume=getattr(c, 'volume', None)) for c in items]
    try:
        raw = rows(source.nifty_intraday_1m(now=now))
    except Exception as exc:
        raise ValueError('TODAY_CANDLE_FETCH_FAILED:' + type(exc).__name__) from None
    through = min(now.replace(second=0, microsecond=0), datetime.combine(day,time(15,30),tzinfo=IST))
    research = partial_replay(e, day, raw, warm, through)
    research['warmup_coverage'] = coverage
    (args.output/'today-research.json').write_text(json.dumps(research, indent=2, default=str)+'\n')
    print('\nFRESH RESEARCH RESULTS:', flush=True)
    for trade in research['trades']:
        print(json.dumps(trade), flush=True)
    print('Open research trade:', json.dumps(research['open_trade']), flush=True)
    print('Closed NIFTY points:', round(research['closed_points'],2), flush=True)
    print('Research output:', args.output/'today-research.json', flush=True)
    report = dict(status='VERIFIED_WARMUP_PREPARED', session_date=day.isoformat(),
        strategy_version=e.VERSION, repo=str(args.repo.resolve()), coverage=coverage,
        prepared_cache_sha256={p.name: __import__('hashlib').sha256(p.read_bytes()).hexdigest()
                               for p in sorted(root.glob('????-??-??.json'))},
        installed_files_modified=False, services_restarted=False, broker_orders_sent=False,
        note='Research may differ from current live state; installation requires after-close flat state.')
    (args.output/'preparation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

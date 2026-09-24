"""Opt-in read-only historical parity capture, separately from live worker.

Uses Upstox historical APIs; failures are evidence gaps, not synthetic rows.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from .hilega_milega_functional_parity_replay_v1 import HilegaMilegaHistoricalFunctionalParityReplayV1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Generate separate historical audit for real-session parity')
    parser.add_argument('--session-date', required=True, type=date.fromisoformat)
    parser.add_argument('--expiry', required=True, type=date.fromisoformat)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--warmup-calendar-days', default=45, type=int)
    args = parser.parse_args(argv)
    if args.expiry < args.session_date:
        parser.error('expiry cannot precede session date')
    from dotenv import load_dotenv
    from .gateways import UpstoxGateway
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    args.output_root.mkdir(parents=True, exist_ok=True)
    token = os.getenv('UPSTOX_ACCESS_TOKEN', '').strip()
    if not token:
        print('UNAVAILABLE: UPSTOX_ACCESS_TOKEN missing; no historical replay performed')
        return 2
    gateway = UpstoxGateway(token)
    try:
        replay = HilegaMilegaHistoricalFunctionalParityReplayV1(
            gateway=gateway, session_date=args.session_date, option_expiry=args.expiry,
            output_root=args.output_root, warmup_calendar_days=args.warmup_calendar_days)
        summary = replay.run()
        # Capture source rows that were actually returned, not assumed available.
        def digest(rows):
            canon = [dict(timestamp=r.timestamp.isoformat(), open=r.open, high=r.high,
                          low=r.low, close=r.close, volume=r.volume) for r in rows]
            raw = json.dumps(canon, sort_keys=True, separators=(',', ':')).encode()
            return {'count': len(canon), 'sha256': hashlib.sha256(raw).hexdigest()}
        selected_baskets = [row.get('payload', {}) for row in replay.coordinator.step_audit.read_all()
                            if row.get('stage') == 'OPTION_CANDIDATE_SET']
        manifest = {
            'model': 'HILEGA_MILEGA_PHASE7D_CAPTURE_MANIFEST_V1',
            'capture_utc': datetime.now(timezone.utc).isoformat(),
            'session_date': args.session_date.isoformat(), 'expiry': args.expiry.isoformat(),
            'source': replay.sources.underlying_source,
            'request_acquisition_date_ist': replay.sources.acquisition_today.isoformat(),
            'option_contract_source': replay.sources.option_contract_source,
            'option_contract_catalog_ce': replay.sources.option_contract_coverage,
            'signal_time_five_strike_baskets': selected_baskets,
            'option_candle_sources': replay.sources.option_candle_sources,
            'note': 'Historical broker responses do not prove original live response availability timing.',
            'underlying': {**digest(replay.sources._underlying),
                           'first': replay.sources._underlying[0].timestamp.isoformat(),
                           'last': replay.sources._underlying[-1].timestamp.isoformat()},
            'options': {key: {**digest(rows),
                              'first': rows[0].timestamp.isoformat() if rows else None,
                              'last': rows[-1].timestamp.isoformat() if rows else None,
                              'source': replay.sources.option_candle_sources.get(key)}
                        for key, rows in sorted(replay.sources._option_cache.items())},
            'summary': summary,
            'missing_data': [x for x in selected_baskets if x.get('status') != 'AVAILABLE'
                             or x.get('issue')],
        }
        (args.output_root/'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(json.dumps({'status': 'CAPTURED', 'output_root': str(args.output_root),
                          'summary': summary}, indent=2))
        return 0
    except Exception as exc:
        # Do not hide missing broker entitlement, contracts or exact option data.
        failure = {'status': 'UNAVAILABLE', 'error_type': type(exc).__name__,
                   'reason': str(exc), 'session_date': args.session_date.isoformat()}
        (args.output_root/'capture-unavailable.json').write_text(json.dumps(failure, indent=2) + '\n')
        print(json.dumps(failure, indent=2))
        return 2
    finally:
        gateway.close()


if __name__ == '__main__':
    raise SystemExit(main())

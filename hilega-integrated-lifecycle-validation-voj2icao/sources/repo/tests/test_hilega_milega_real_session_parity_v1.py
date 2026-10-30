from datetime import datetime
import json

from market_lab.domain import IST
from market_lab.hilega_milega_real_session_parity_v1 import compare_audit_files, main
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


def audit(path, data, *, version='1.0.0'):
    store = ShadowStepAuditStoreV1(path)
    for ts, stage, status, payload in data:
        payload = {'strategy_id': 'HILEGA_MILEGA_BULLISH_SHADOW_V1',
                   'strategy_version': version, **payload}
        store.append(event_time=datetime.fromisoformat(ts), checkpoint=datetime.fromisoformat(ts),
                     stage=stage, status=status, payload=payload)


def sample():
    return [('2026-09-23T10:15:00+05:30', 'INDICATOR_CALCULATION', 'READY',
             {'close': 23393.25, 'rsi9': 60., 'ema3_rsi': 58., 'wma21_rsi': 55.}),
            ('2026-09-23T10:15:00+05:30', 'STRATEGY_TRANSITION', 'ENTRY',
             {'event_type': 'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21', 'price': 23393.25,
              'state_before': 'PATH1_IDLE', 'state_after': 'BULLISH_ACTIVE'})]


def test_identical_verified_audits_are_parity_pass(tmp_path):
    h, l = tmp_path/'historical.jsonl', tmp_path/'live.jsonl'
    audit(h, sample())
    audit(l, sample())
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23', historical_build_id='test-build', live_build_id='test-build')
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'  # Entry without options cannot certify full parity
    assert result['core']['compared_events'] == 2
    assert result['options']['compared_events'] == 0


def test_detect_indicator_mismatch_exact_field(tmp_path):
    h, l = tmp_path/'historical.jsonl', tmp_path/'live.jsonl'
    audit(h, sample())
    changes = sample()
    changes[0][3]['rsi9'] = 61
    audit(l, changes)
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23', historical_build_id='test-build', live_build_id='test-build')
    assert result['status'] == 'FAIL'
    assert result['core']['mismatches'][0]['differences'][0]['field'] == 'payload.rsi9'


def test_missing_older_bootstrap_coverage_is_insufficient(tmp_path):
    h, l = tmp_path/'historical.jsonl', tmp_path/'live.jsonl'
    audit(h, sample())
    audit(l, sample()[1:])
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23', historical_build_id='test-build', live_build_id='test-build')
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert result['core']['missing_in_live']


def test_live_restart_duplicate_conflict_detected(tmp_path):
    h, l = tmp_path/'historical.jsonl', tmp_path/'live.jsonl'
    audit(h, sample())
    audit(l, sample())
    audit(l, [('2026-09-23T10:15:00+05:30', 'INDICATOR_CALCULATION', 'READY',
               {'close': 23393.25, 'rsi9': 98, 'ema3_rsi': 58., 'wma21_rsi': 55.})])
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23', historical_build_id='test-build', live_build_id='test-build')
    assert result['status'] == 'FAIL'
    assert result['core']['duplicate_conflicts']['live']


def test_version_mismatch_refuses_parity(tmp_path):
    h, l = tmp_path/'historical.jsonl', tmp_path/'live.jsonl'
    audit(h, sample())
    audit(l, sample(), version='1.0.1')
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23', historical_build_id='test-build', live_build_id='test-build')
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert 'VERSION_MISMATCH' in result['preconditions'][0]


def test_tampered_chain_never_compares(tmp_path):
    h, l = tmp_path/'historical.jsonl', tmp_path/'live.jsonl'
    audit(h, sample())
    audit(l, sample())
    raw = l.read_text()
    l.write_text(raw.replace('23393.25', '23394.25', 1))
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23', historical_build_id='test-build', live_build_id='test-build')
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert 'INVALID_HASH_CHAIN' in result['preconditions'][0]


def test_option_causal_entry_differences_fail(tmp_path):
    h, l = tmp_path/'historical.jsonl', tmp_path/'live.jsonl'
    payload = {'signal_bar': '2026-09-23T11:30:00+05:30',
               'signal_boundary': '2026-09-23T11:35:00+05:30',
               'expiry': '2026-09-29', 'atm': 23450., 'status': 'ACTIVE',
               'legs': [{'entry_open': 117.1, 'strike': 23450}]}
    base = [('2026-09-23T11:30:00+05:30', 'INDICATOR_CALCULATION', 'READY', {'rsi9': 50.}),
            ('2026-09-23T11:30:00+05:30', 'OPTION_SHADOW_LIFECYCLE_START', 'PASS', payload)]
    audit(h, base)
    changed = [(base[0])] + [(base[1][0], base[1][1], base[1][2], {**payload, 'legs': [{'entry_open': 117.2, 'strike':23450}]})]
    audit(l, changed)
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23', historical_build_id='test-build', live_build_id='test-build')
    assert result['status'] == 'FAIL'
    assert result['options']['mismatches'][0]['differences'][0]['field'] == 'payload.legs[0].entry_open'


def test_cli_writes_report_and_exit_code(tmp_path):
    h, l, report = tmp_path/'historical.jsonl', tmp_path/'live.jsonl', tmp_path/'report.json'
    audit(h, sample())
    audit(l, sample())
    code = main(['--historical-audit', str(h), '--live-audit', str(l),
                 '--session-date', '2026-09-23', '--output', str(report)])
    assert code == 2
    assert json.loads(report.read_text())['status'] == 'INSUFFICIENT_EVIDENCE'


def test_full_parity_pass_requires_option_evidence_and_same_build(tmp_path):
    h, l = tmp_path/'h.jsonl', tmp_path/'l.jsonl'
    row = ('2026-09-23T10:15:00+05:30', 'OPTION_SHADOW_LIFECYCLE_START', 'PASS',
           {'signal_bar': '2026-09-23T10:15:00+05:30', 'signal_boundary': '2026-09-23T10:20:00+05:30',
            'expiry': '2026-09-29', 'atm': 23400., 'status': 'ACTIVE', 'legs': [{'entry_open': 100.}]})
    audit(h, sample() + [row])
    audit(l, sample() + [row])
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23',
                                historical_build_id='same', live_build_id='same')
    assert result['status'] == 'PASS'


def test_unverified_build_cannot_be_certified(tmp_path):
    h, l = tmp_path/'h.jsonl', tmp_path/'l.jsonl'
    audit(h, sample())
    audit(l, sample())
    result = compare_audit_files(historical_path=h, live_path=l, session_date='2026-09-23')
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert any('BUILD_ID_UNVERIFIED' in x for x in result['preconditions'])

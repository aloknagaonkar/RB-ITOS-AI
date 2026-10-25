from market_lab.hilega_v2_replay_presentation_v1 import project_session, validated_session
import pytest

def sample():
    return dict(policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='bullish-gap2-full-wma2-1.0.0',
      trades=[dict(trade_id='x',direction='BULLISH',signal_time='2026-10-16T09:20:00+05:30',entry_time='2026-10-16T09:55:00+05:30')],
      policy_events=[dict(time='2026-10-16T09:55:00+05:30',direction='BULLISH',passed=True,signal_time='2026-10-16T09:45:00+05:30')],
      audit=[dict(checkpoint='2026-10-16T14:55:00+05:30',owner_after='NONE',checks=[dict(direction='BULLISH',status='WAIT')],transitions=[])])

def test_cutoff_not_candidate():
    out=project_session(sample())
    row=out['reports'][0]
    assert row['strategy']['state_after']=='SESSION_LOCKED'
    assert row['strategy']['events_emitted']==['SESSION_CLOSED']
    assert 'no further entries' in row['strategy']['rule_description']

def test_setup_and_qualified_are_distinct():
    out=project_session(sample())
    t=out['trades'][0]
    assert t['setup_available'][11:16]=='09:20'
    assert t['qualified_signal_time'][11:16]=='09:45'
    assert t['entry_time'][11:16]=='09:55'

def test_does_not_rewrite_original_evidence():
    original=sample();project_session(original)
    assert original['audit'][0]['checks']
    assert 'qualified_signal_time' not in original['trades'][0]

def test_validated_missing_fails_without_fallback(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError,match='VALIDATED_REPLAY_NOT_AVAILABLE'):
        validated_session('2026-10-16')

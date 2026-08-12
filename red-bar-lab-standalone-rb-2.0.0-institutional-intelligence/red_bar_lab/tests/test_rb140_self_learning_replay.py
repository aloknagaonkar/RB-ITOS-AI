from red_bar_lab.services.historical_decision_replay import HistoricalDecisionReplayService, DecisionReplayRow


def test_verdict_matrix():
    s=HistoricalDecisionReplayService
    assert s._verdict('WOULD_TAKE','WIN')=='CORRECT_TAKE'
    assert s._verdict('WOULD_TAKE','LOSS')=='FALSE_POSITIVE'
    assert s._verdict('WOULD_WAIT','WIN')=='MISSED_OPPORTUNITY'
    assert s._verdict('WOULD_WAIT','LOSS')=='CORRECT_SKIP'
    assert s._verdict('WOULD_BLOCK','WIN')=='INCORRECT_BLOCK'
    assert s._verdict('WOULD_BLOCK','LOSS')=='CORRECT_BLOCK'


def test_missed_opportunity_attributes_primary_confidence_threshold():
    attr, rec = HistoricalDecisionReplayService._learning_attribution(
        verdict='MISSED_OPPORTUNITY', blocker='FINAL_CONFIDENCE=59.11<MIN=70.00',
        shadow_decision='WAIT', shadow_adjustment=0.0,
        vwap_ok=None, ema_ok=True, momentum_ok=True,
    )
    assert attr == 'CONFIDENCE_THRESHOLD'
    assert 'minimum confidence threshold' in rec


def _row(verdict, attr='NO'):
    return DecisionReplayRow(
        signal_id='s',timestamp='t',level_type='L',direction='BULLISH',option_side='CE',
        lifecycle_state='NEW',lifecycle_action='EVALUATE',market_session='MORNING',
        primary_confidence_pct=70,shadow_decision='WAIT',shadow_confidence_pct=50,
        agreement='INFORMATIONAL',shadow_adjustment_pct=0,final_confidence_pct=70,expectancy_pct=5,
        decision='WAIT',execution='WOULD_WAIT',blocker='FINAL_CONFIDENCE',data_fidelity='POINT',
        vwap_ok=None,ema_ok=True,momentum_ok=True,volume_score=7.5,oi_score=5,
        outcome_points=10,outcome_result='WIN',verdict=verdict,
        learning_attribution=attr,learning_recommendation='r',
    )


def test_learning_summary_is_advisory():
    recs, accuracy = HistoricalDecisionReplayService._aggregate_learning([
        _row('MISSED_OPPORTUNITY','CONFIDENCE_THRESHOLD'),
        _row('CORRECT_SKIP'),
    ])
    assert accuracy == 50.0
    assert any('Confidence calibration' in r for r in recs)
    assert all('auto' not in r.lower() or 'changing' in r.lower() for r in recs)

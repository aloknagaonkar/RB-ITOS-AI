import json
from hilega_vwap_signal_review.collect import signals
from market_lab import hilega_vwap_audit_v1 as inspection

AT='2026-10-15T12:50:00+05:30'


def audit(tmp_path, **updates):
    path=tmp_path/'audit.jsonl'
    payload=dict(decision_timestamp=AT,strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',
                 trade_owner_before='NONE',trade_owner_after='NONE',setup_attempts=[],
                 event_details=[],bullish_armed=False,bearish_armed=False)
    payload.update(updates)
    path.write_text(json.dumps(dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=payload))+'\n')
    return path


def test_carried_bullish_candidate_without_new_setup(tmp_path):
    rows=signals(audit(tmp_path,bullish_armed=True),'2026-10-15')
    assert len(rows)==1
    assert rows[0]['kind']=='ARMED_CANDIDATE' and rows[0]['direction']=='BULLISH'
    assert rows[0]['context_evidence']['bullish_armed'] is True


def test_carried_bearish_candidate_without_owner(tmp_path):
    rows=signals(audit(tmp_path,bearish_armed=True),'2026-10-15')
    assert [(r['kind'],r['direction']) for r in rows]==[('ARMED_CANDIDATE','BEARISH')]


def test_opposite_candidate_kept_separate_from_active_position(tmp_path):
    rows=signals(audit(tmp_path,bullish_armed=True,trade_owner_before='BEARISH',trade_owner_after='BEARISH'),'2026-10-15')
    assert {(r['context_type'],r['direction']) for r in rows}=={
        ('ARMED_CANDIDATE','BULLISH'),('ACTIVE_POSITION','BEARISH')}


def test_both_flags_produce_two_candidates_not_arbitrary_direction(tmp_path):
    rows=signals(audit(tmp_path,bullish_armed=True,bearish_armed=True),'2026-10-15')
    assert {(r['kind'],r['direction']) for r in rows}=={
        ('ARMED_CANDIDATE','BULLISH'),('ARMED_CANDIDATE','BEARISH')}


def test_no_direction_stays_neutral(tmp_path):
    rows=signals(audit(tmp_path),'2026-10-15')
    assert rows[0]['direction']=='NONE' and rows[0]['kind']=='DECISION_CHECKPOINT'


def test_new_setup_does_not_duplicate_same_candidate(tmp_path):
    rows=signals(audit(tmp_path,bullish_armed=True,setup_attempts=[dict(direction='BULLISH',source='V1_CANONICAL')]),'2026-10-15')
    assert len(rows)==1 and rows[0]['kind']=='SETUP'


def test_false_text_is_not_an_armed_flag(tmp_path):
    rows=signals(audit(tmp_path,bullish_armed='false'),'2026-10-15')
    assert rows[0]['direction']=='NONE'


def test_recovered_candidate_does_not_override_original_processed_state(tmp_path):
    path=audit(tmp_path)
    recovered=json.loads(path.read_text());recovered['status']='RECOVERED'
    recovered['payload']['bullish_armed']=True
    with path.open('a') as stream:stream.write(json.dumps(recovered)+'\n')
    rows=signals(path,'2026-10-15')
    assert len(rows)==1 and rows[0]['direction']=='NONE'


def test_processed_candidate_overrides_recovered_no_direction(tmp_path):
    path=audit(tmp_path,bullish_armed=True)
    processed=json.loads(path.read_text());recovered=json.loads(path.read_text())
    recovered['status']='RECOVERED';recovered['payload']['bullish_armed']=False
    path.write_text(json.dumps(recovered)+'\n'+json.dumps(processed)+'\n')
    rows=signals(path,'2026-10-15')
    assert len(rows)==1 and rows[0]['kind']=='ARMED_CANDIDATE'


def evidence(direction='BULLISH',kind='ARMED_CANDIDATE',**updates):
    row=dict(signal_time=AT,kind=kind,direction=direction,source='DIRECTIONAL_DECISION',
             status='AVAILABLE',basis='NIFTY_FUTURES_SESSION_5M_TYPICAL_PRICE_PROXY',
             vwap=22894.69,futures_close=23024.5,distance_points=129.81,
             candle_available_at=AT,context_evidence=dict(bullish_armed=True,bearish_armed=False))
    row.update(updates);return row


def inspect_rows(tmp_path, rows):
    journal=tmp_path/'signal-vwap-observations.jsonl'
    journal.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    return inspection.inspect(AT,journal,tmp_path/'no-report')


def test_screenshot_candidate_agrees_with_vwap_and_supersedes_neutral(tmp_path):
    neutral=evidence(direction='NONE',kind='DECISION_CHECKPOINT')
    result=inspect_rows(tmp_path,[neutral,evidence()])
    assert len(result['rows'])==1 and result['superseded_context_rows']==1
    assert result['rows'][0]['direction_agrees_with_vwap'] is True


def test_bearish_candidate_above_vwap_is_opposed(tmp_path):
    row=evidence(direction='BEARISH',context_evidence=dict(bearish_armed=True))
    assert inspect_rows(tmp_path,[row])['rows'][0]['direction_agrees_with_vwap'] is False


def test_active_position_not_suppressed_by_opposite_candidate(tmp_path):
    position=evidence(direction='BEARISH',kind='DECISION_CHECKPOINT')
    result=inspect_rows(tmp_path,[position,evidence()])
    assert len(result['rows'])==2


def test_candidate_requires_explicit_matching_arm_evidence(tmp_path):
    result=inspect_rows(tmp_path,[evidence(context_evidence=dict(bullish_armed=False))])
    assert not result['rows'] and result['issues']


def test_duplicate_candidate_journal_rows_are_idempotent_in_inspection(tmp_path):
    assert len(inspect_rows(tmp_path,[evidence(),evidence()])['rows'])==1


def test_repair_reuses_recorded_prices_and_is_idempotent(tmp_path):
    from types import SimpleNamespace
    from hilega_vwap_signal_review.collect import repair_context
    path=audit(tmp_path,bullish_armed=True)
    journal=tmp_path/'signal-vwap-observations.jsonl'
    neutral=evidence(direction='NONE',kind='DECISION_CHECKPOINT',instrument_key='NSE_FO|48704',price_position='ABOVE')
    journal.write_text(json.dumps(neutral)+'\n')
    args=SimpleNamespace(audit=path,output=tmp_path,dates=['2026-10-15'])
    repair_context(args);repair_context(args)
    rows=[json.loads(line) for line in journal.read_text().splitlines()]
    assert len(rows)==2 and rows[0]==neutral
    assert rows[1]['kind']=='ARMED_CANDIDATE'
    assert rows[1]['vwap']==neutral['vwap'] and rows[1]['direction_agrees_with_vwap'] is True
    result=inspection.inspect(AT,journal,tmp_path/'missing-report')
    assert len(result['rows'])==1 and result['rows'][0]['kind']=='ARMED_CANDIDATE'


def test_repair_never_uses_another_checkpoint(tmp_path):
    from types import SimpleNamespace
    from hilega_vwap_signal_review.collect import repair_context
    path=audit(tmp_path,bullish_armed=True)
    journal=tmp_path/'signal-vwap-observations.jsonl'
    source=evidence(signal_time='2026-10-15T12:49:00+05:30',candle_available_at='2026-10-15T12:45:00+05:30',
                    kind='DECISION_CHECKPOINT',direction='NONE',instrument_key='NSE_FO|48704',price_position='ABOVE')
    journal.write_text(json.dumps(source)+'\n')
    repair_context(SimpleNamespace(audit=path,output=tmp_path,dates=['2026-10-15']))
    assert len(journal.read_text().splitlines())==1

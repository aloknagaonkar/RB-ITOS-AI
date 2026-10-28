cd "$HOME/RB-ITOS-AI" || exit 1
.venv/bin/python - <<'PY'
import ast
import hashlib
from pathlib import Path
import shutil
import tempfile

path = Path("tests/test_hilega_wma_gap_live_v2.py")
raw = path.read_bytes()
blob = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
if blob != "6af444c2823e5743b9924acee3d4716bf54877a6":
    raise SystemExit("STOP: test file differs from reviewed baseline")

replacements = {
"test_exit_boundary_can_reverse_only_with_two_strong_minutes": r'''
def test_exit_boundary_waits_for_post_signal_arm_and_later_persistence():
    g = WmaGapGate()
    g.owner = 'BULLISH'
    g.active = {'time': T-timedelta(minutes=10), 'price': 100}
    g.previous = {
        'minute': T-timedelta(minutes=1),
        'snapshot': obs(35,40), 'wma_change': -.9,
    }
    closed = g.close(ev(BX), T+timedelta(minutes=1), 99)
    assert closed.points == -1
    g.signal(ev(SE), T+timedelta(minutes=1))

    events, checks = g.evaluate(
        minute=T, current=obs(33,39), reference=obs(41,40),
        price=99, exit_boundary=True,
    )
    assert events == [] and g.owner == 'NONE'
    assert 'WAIT_FIRST_POST_SIGNAL_MINUTE' in checks[0]['reasons']
    assert checks[0]['same_exit_boundary_confirmation'] is False

    events, checks = g.evaluate(
        minute=T+timedelta(minutes=1), current=obs(31,38.8),
        reference=obs(41,40), price=98,
    )
    assert events == []
    assert g.pending['BEARISH']['armed_at'] == T+timedelta(minutes=1)
    assert 'WAIT_LATER_PERSISTENCE' in checks[0]['reasons']

    events, checks = g.evaluate(
        minute=T+timedelta(minutes=2), current=obs(29,38.6),
        reference=obs(41,40), price=97,
    )
    assert len(events) == 1 and g.owner == 'BEARISH'
    assert checks[0]['persistence_pass'] is True
    assert checks[0]['same_exit_boundary_confirmation'] is False
    assert events[0].entry_time == T+timedelta(minutes=3)
''',
"test_exit_boundary_does_not_bypass_strength_or_contiguity": r'''
@pytest.mark.parametrize('previous_change,previous_minute',[
    (.9,T-timedelta(minutes=1)),
    (-.2,T-timedelta(minutes=1)),
    (-.9,T-timedelta(minutes=2)),
])
def test_exit_boundary_does_not_bypass_strength_or_contiguity(previous_change,previous_minute):
    g = WmaGapGate()
    g.signal(ev(SE,at=T-timedelta(minutes=10)), T-timedelta(minutes=5))
    g.pending['BEARISH']['armed_at'] = T-timedelta(minutes=2)
    g.previous = {
        'minute': previous_minute, 'snapshot': obs(35,40),
        'wma_change': previous_change,
    }
    events, checks = g.evaluate(
        minute=T, current=obs(33,39), reference=obs(41,40),
        price=99, exit_boundary=True,
    )
    assert events == []
    assert checks[0]['confirmation_window_pass'] is True
    assert checks[0]['wma_threshold_pass'] is True
    assert checks[0]['persistence_pass'] is False
    assert 'WAIT_LATER_PERSISTENCE' in checks[0]['reasons']
    assert 'BEARISH' in g.pending
''',
"test_live_adapter_emits_same_boundary_exit_then_entry_with_exact_times": r'''
def test_live_adapter_exits_then_confirms_replacement_on_later_minute(tmp_path):
    c = HilegaWmaGapLiveCoordinatorV2(
        market_sources=SimpleNamespace(), option_expiry=None,
        step_audit_path=tmp_path/'audit', health_path=tmp_path/'health',
    )
    t = T+timedelta(minutes=4)
    exit_at = t+timedelta(minutes=1)
    snapshots = {99:obs(33,40),98:obs(31,39.8),97:obs(29,39.6)}
    c.canonical.bullish.indicators = SimpleNamespace(
        update=lambda close:snapshots[close]
    )
    c.canonical.bullish.previous_indicators = obs(45,41)
    c.canonical.on_bar = Mock(return_value=DirectionalDecision(
        T.isoformat(),'BULLISH','BEARISH',(ev(BX),ev(SE)),(),
        'IDLE','ACTIVE',False,False,
    ))
    c.gate.owner = 'BULLISH'
    c.gate.active = {'time':T-timedelta(minutes=5),'price':100}
    c.gate.previous = {
        'minute':t-timedelta(minutes=1),
        'snapshot':obs(35,41),'wma_change':-.9,
    }
    calls = Mock()
    c._close_option = calls.close
    c._start_option = calls.start
    bar = FiveMinuteBar(T,100,101,99,99,None)

    def step(at,price):
        c._advance(SimpleNamespace(
            timestamp=at,open=price,high=price,low=price,close=price,
        ),{T:bar},recovered=False)

    step(t,99)
    assert [call[0] for call in calls.mock_calls] == ['close']
    assert calls.close.call_args.kwargs['exit_boundary'] == exit_at
    assert c.gate.owner == 'NONE'

    step(t+timedelta(minutes=1),98)
    assert [call[0] for call in calls.mock_calls] == ['close']
    assert c.gate.owner == 'NONE'

    step(t+timedelta(minutes=2),97)
    entry_at = t+timedelta(minutes=3)
    assert [call[0] for call in calls.mock_calls] == ['close','start']
    assert calls.start.call_args.kwargs['now'] == entry_at
    assert calls.start.call_args.kwargs['bar'].ts == T
    assert calls.start.call_args.kwargs['event'].entry_time == entry_at
    assert c.gate.owner == 'BEARISH'
    c.canonical.on_bar.assert_called_once()
    assert c.step_audit.verify_chain() == (True,None)

    payloads = [
        r['payload'] for r in c.step_audit.read_all()
        if r['stage'] == 'DIRECTIONAL_DECISION'
    ]
    assert [p['accepted_events'] for p in payloads] == [[BX],[],[SE]]
    assert payloads[0]['decision_timestamp'] == exit_at.isoformat()
    assert payloads[-1]['decision_timestamp'] == entry_at.isoformat()
''',
}

text = raw.decode()
tree = ast.parse(text)
edits = []
for name, replacement in replacements.items():
    matches = [
        n for n in tree.body
        if isinstance(n,ast.FunctionDef) and n.name == name
    ]
    if len(matches) != 1:
        raise SystemExit("STOP: function anchor mismatch: "+name)
    node = matches[0]
    first = min([node.lineno]+[d.lineno for d in node.decorator_list])
    edits.append((first-1,node.end_lineno,replacement.strip()+"\n"))

lines = text.splitlines(keepends=True)
for start,end,replacement in sorted(edits,reverse=True):
    lines[start:end] = [replacement]
updated = "".join(lines)
ast.parse(updated,filename=str(path))

backup = Path(tempfile.mkdtemp(
    prefix="hilega-wma-test-update-",dir="backups"
))
shutil.copy2(path,backup/path.name)
path.write_text(updated)
print("Updated test file:",path)
print("Original backup:",backup/path.name)
print("Runtime strategy source unchanged. Tests not executed.")
PY
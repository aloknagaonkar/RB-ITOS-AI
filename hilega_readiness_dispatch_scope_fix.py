"""Scope historical dispatch alerts to their session. No order/journal mutations."""
import argparse
import importlib.util
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

TARGET=Path('backend/market_lab/operational_readiness_v1.py')
OLD="    alerts=previous.get('alerts',[]);old={a['id']:a for a in alerts if a.get('active')};new=[];events=list(previous.get('notifications',[]))"
NEW='''    # HILEGA_DISPATCH_SESSION_SCOPE_V1: retain history without claiming recovery.
    alerts=[];archived_dispatch=[]
    for original in previous.get('alerts',[]):
        alert=original
        if alert.get('active') and str(alert.get('id','')).startswith('DISPATCH_'):
            try:
                stamp=datetime.fromisoformat(alert['id'][9:])
                prior=stamp.tzinfo is not None and stamp.astimezone(IST).date()<now.astimezone(IST).date()
            except (ValueError,TypeError):
                prior=False
            if prior:
                alert=dict(alert,active=False,historical_unresolved=True,
                           archived_at=now.isoformat(),
                           archive_reason='PRIOR_SESSION_DISPATCH_UNRESOLVED_NOT_A_CURRENT_SESSION_CHECK')
                archived_dispatch.append(dict(kind='HISTORICAL_UNRESOLVED',timestamp=now.isoformat(),
                                              message='Archived prior-session alert; dispatch remains unresolved: '+alert['id']))
        alerts.append(alert)
    old={a['id']:a for a in alerts if a.get('active')};new=[]
    events=list(previous.get('notifications',[]))+archived_dispatch'''


def prepared():
    source=TARGET.read_text()
    if NEW in source:return source,source
    if source.count(OLD)!=1:raise SystemExit('SOURCE_DIFFERS_NO_FILES_CHANGED: '+str(TARGET))
    result=source.replace(OLD,NEW,1);compile(result,str(TARGET),'exec')
    return source,result


def tests(source):
    with tempfile.TemporaryDirectory(prefix='hilega-readiness-scope-') as folder:
        stage=Path(folder)/'readiness.py';stage.write_text(source)
        spec=importlib.util.spec_from_file_location('readiness_scope_checks',stage)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        now=datetime.fromisoformat('2026-10-16T09:10:00+05:30')
        def alert(identity,component='Sandbox dispatch'):
            return dict(id=identity,component=component,message='Original evidence',active=True,
                        first_seen='2026-10-14T14:52:34+05:30',last_seen='2026-10-14T14:52:34+05:30',
                        last_reminded='2026-10-14T14:52:34+05:30',last_successful=None)
        old=alert('DISPATCH_2026-10-14T14:52:00+05:30')
        today=alert('DISPATCH_2026-10-16T09:00:00+05:30')
        future=alert('DISPATCH_2026-10-17T09:00:00+05:30')
        malformed=alert('DISPATCH_BAD_TIMESTAMP')
        previous=dict(alerts=[old,today,future,malformed],notifications=[])
        live=dict(active_strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT')
        worker=dict(running=True,armed=True,session_date='2026-10-16',strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',kill_switch=False,uncertain_requests=0)
        warm=dict(ready=True,session_date='2026-10-16',analytics_probe=dict(status='PASS',checked_at=now.isoformat()))
        with patch.dict(os.environ,dict(UPSTOX_ACCESS_TOKEN='TEST_NOT_SENT',UPSTOX_SANDBOX_ACCESS_TOKEN='TEST_NOT_SENT',LIVE_SHADOW_STRATEGY='HILEGA_V2_ALIGNMENT_DUAL_EXIT')):
            result=module.evaluate(now,live,dict(worker=worker),warm,dict(missing_dispatch=[],resolved_dispatch=[]),{},previous)
            by_id={a['id']:a for a in result['alerts']}
            assert by_id[old['id']]['active'] is False
            assert by_id[old['id']]['historical_unresolved'] is True
            assert by_id[old['id']]['last_successful'] is None and 'recovered_at' not in by_id[old['id']]
            assert by_id[old['id']]['last_seen']==old['last_seen'] and old['active'] is True
            assert all(by_id[a['id']]['active'] is True for a in (today,future,malformed))
            next_result=module.evaluate(now,live,dict(worker=worker),warm,dict(missing_dispatch=[],resolved_dispatch=[]),{},result)
            assert len([n for n in next_result['notifications'] if n['kind']=='HISTORICAL_UNRESOLVED'])==1
            clean=module.evaluate(now,live,dict(worker=worker),warm,dict(missing_dispatch=[],resolved_dispatch=[]),{},dict(alerts=[old]))
            assert clean['status']=='READY'
            assert any(c['id']=='SANDBOX' and c['status']=='PASS' for c in clean['checks'])
            bad=module.evaluate(now,live,dict(worker=dict(worker,uncertain_requests=1)),warm,{}, {},dict(alerts=[old]))
            assert bad['status']=='NOT_READY' and any(c['id']=='SANDBOX' and c['status']=='FAIL' for c in bad['checks'])
        print(json.dumps(dict(status='CHECKS_PASSED',network_requests=False,orders_sent=False,
                              checks=['prior_alert_archived','history_preserved','no_fake_recovery','current_alert_retained',
                                      'future_alert_retained','malformed_alert_retained','idempotent','healthy_today_ready','uncertain_request_still_blocks'])))


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group()
    group.add_argument('--check',action='store_true');group.add_argument('--test',action='store_true');args=parser.parse_args()
    original,result=prepared()
    print(json.dumps(dict(status='VALIDATED',file=str(TARGET),orders_sent=False,tests_run=False)))
    if args.check:return
    if args.test:tests(result);return
    if original==result:print('ALREADY_APPLIED');return
    backup=Path('backups')/('readiness-dispatch-scope-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True);shutil.copy2(TARGET,backup/TARGET.name)
    if TARGET.read_text()!=original:raise SystemExit('SOURCE_CHANGED_NO_FILES_WRITTEN')
    temp=TARGET.with_name(TARGET.name+'.dispatch-scope.tmp')
    with temp.open('w') as stream:
        stream.write(result);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,TARGET)
    print(json.dumps(dict(status='APPLIED',backup=str(backup),state_rewritten=False,journals_changed=False,orders_sent=False)))


if __name__=='__main__':main()

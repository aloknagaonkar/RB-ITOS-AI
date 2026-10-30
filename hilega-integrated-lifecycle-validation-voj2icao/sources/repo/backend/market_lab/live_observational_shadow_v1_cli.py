import argparse, json
from market_lab.live_observational_shadow_v1 import AuditStore, write_ledger, daily_summary, reconstruct_states

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    v=sub.add_parser('verify'); v.add_argument('--events',required=True)
    l=sub.add_parser('ledger'); l.add_argument('--events',required=True); l.add_argument('--output',required=True)
    d=sub.add_parser('daily-summary'); d.add_argument('--events',required=True); d.add_argument('--session-date',required=True); d.add_argument('--output',required=True)
    a=ap.parse_args()
    if a.cmd=='verify':
        ok,issue=AuditStore(a.events).verify_chain(); print(json.dumps({'ok':ok,'issue':issue})); return 0 if ok else 2
    if a.cmd=='ledger':
        rows=write_ledger(a.events,a.output); print(json.dumps({'rows':len(rows),'output':a.output})); return 0
    states=reconstruct_states(AuditStore(a.events).read_all()).values(); report=daily_summary(states,a.session_date); open(a.output,'w').write(json.dumps(report,indent=2)+'\n'); print(json.dumps(report,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

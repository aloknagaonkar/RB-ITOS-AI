from __future__ import annotations
import argparse,json
from .historical_option_intrabar_replay_v1 import replay_intrabar_date
from .session_data_gate_v1 import validate_session,DEFAULT_FUTURES_CSV

def main():
    p=argparse.ArgumentParser(); p.add_argument('--session-date',required=True); p.add_argument('--data-root',default='data'); p.add_argument('--futures-csv',default=str(DEFAULT_FUTURES_CSV)); p.add_argument('--events',choices=('none','exits','all'),default='exits'); a=p.parse_args()
    gate=validate_session(a.session_date,data_root=a.data_root,futures_csv=a.futures_csv)
    if gate.status!='PASS':
        print(json.dumps({'status':'BLOCKED_BY_DATA_GATE','data_gate':gate.to_dict()},indent=2)); raise SystemExit(2)
    result=replay_intrabar_date(a.session_date,data_root=a.data_root,futures_csv=a.futures_csv)
    payload={'status':'PASS','session_date':a.session_date,'data_gate':gate.to_dict(),'summary':result.summary(),'ohlc_source':result.ohlc_source,'trades':[vars(t) for t in result.trades]}
    if a.events=='all': payload['events']=[vars(e) for e in result.events]
    elif a.events=='exits': payload['events']=[vars(e) for e in result.events if e.event_type in {'PAPER_ENTRY_REJECTED','PAPER_POSITION_OPENED','POSITION_CLOSED'}]
    print(json.dumps(payload,indent=2))
if __name__=='__main__': main()

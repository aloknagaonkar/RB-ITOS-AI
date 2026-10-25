"""Authenticated CLI client for the same workspace API used by the UI.
Only disabled/simulation workspace is supported. Never submits Upstox orders.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlsplit
from urllib.error import HTTPError,URLError
import uuid

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base-url',default='http://127.0.0.1:8123')
    ap.add_argument('--token-file',type=Path)
    ap.add_argument('--env-file',type=Path)
    sub=ap.add_subparsers(dest='action',required=True)
    sub.add_parser('status')
    for name in ('pause-today','resume','reconcile','exit','flatten-and-pause'):
        p=sub.add_parser(name);p.add_argument('--request-id',default=None)
        if name in ('resume','exit'):
            p.add_argument('--expected-version',required=True,type=int);p.add_argument('--session-date',required=True)
        if name=='resume':p.add_argument('--next-signal',action='store_true',required=True)
        if name=='exit':p.add_argument('--position-id',required=True)
    a=ap.parse_args()
    if a.env_file:
        from dotenv import load_dotenv
        load_dotenv(a.env_file,override=False)
    token=os.getenv('HILEGA_PRODUCTION_CONTROL_TOKEN','')
    file=a.token_file or (Path(os.environ['HILEGA_PRODUCTION_CONTROL_TOKEN_FILE']) if os.getenv('HILEGA_PRODUCTION_CONTROL_TOKEN_FILE') else None)
    if file:token=file.read_text().strip()
    if len(token)<32:raise ValueError('CONTROL_KEY_MISSING')
    url=urlsplit(a.base_url)
    if url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        raise ValueError('BASE_URL_INVALID')
    if url.scheme!='https' and not(url.scheme=='http' and url.hostname in ('127.0.0.1','localhost','::1')):
        raise ValueError('HTTPS_OR_LOOPBACK_REQUIRED')
    payload=None
    if a.action!='status':
        action={'pause-today':'pause','resume':'resume','reconcile':'reconcile','exit':'exit','flatten-and-pause':'flatten'}[a.action]
        payload=dict(action=action,request_id=a.request_id or str(uuid.uuid4()),expected_version=getattr(a,'expected_version',None),
            session_date=getattr(a,'session_date',None),position_id=getattr(a,'position_id',None),confirmation='SIMULATION_ONLY')
    req=Request(a.base_url.rstrip('/')+'/api/hilega-production/'+('commands' if payload else 'status'),
        data=json.dumps(payload).encode() if payload else None,method='POST' if payload else 'GET',
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect()).open(req,timeout=10) as r:print(json.dumps(json.load(r),indent=2))
    except HTTPError as exc:
        import re
        reason='REQUEST_REJECTED'
        try:
            detail=json.load(exc).get('detail')
            if isinstance(detail,str) and re.fullmatch('[A-Z0-9_]{1,120}',detail):reason=detail
        except Exception:pass
        # The workspace returns bounded safe error codes, never a raw Upstox body.
        print(json.dumps(dict(status='COMMAND_OR_READ_REJECTED',http_status=exc.code,reason=reason,
            notice='Check latest status; do not assume a timed-out command failed.')));raise SystemExit(2)
    except (URLError,TimeoutError):
        print(json.dumps(dict(status='ACKNOWLEDGEMENT_UNAVAILABLE',notice='No automatic retry. Check server state before another command.')));raise SystemExit(2)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError):print(json.dumps(dict(status='LOCAL_CONFIGURATION_ERROR')));raise SystemExit(2)

"""Only the isolated loopback API. Token is file-based, never a command argument."""
import json,subprocess,sys,uuid
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class Client:
    def __init__(self,base_url,token_file,root,env):
        parsed=urlsplit(base_url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port is None or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:raise ValueError('PRIVATE_LOOPBACK_ONLY')
        self.url=base_url;self.key=Path(token_file);self.root=Path(root);self.env=env
    def status(self):
        req=Request(self.url+'/api/hilega-production/status',headers={'Authorization':'Bearer '+self.key.read_text().strip()})
        with build_opener(NoRedirect()).open(req,timeout=8) as r:return json.load(r)
    def origin_rejected(self):
        req=Request(self.url+'/api/hilega-production/status',headers={'Authorization':'Bearer '+self.key.read_text().strip(),'Origin':'https://invalid.example'})
        try:
            with build_opener(NoRedirect()).open(req,timeout=8):return False
        except HTTPError as exc:return exc.code==403
    def cli(self,action,*extra):
        args=[sys.executable,str(self.root/'scripts/hilega_production_control.py'),'--base-url',self.url,'--token-file',str(self.key),action,*extra]
        r=subprocess.run(args,cwd=self.key.parent,env=self.env,capture_output=True,text=True,timeout=15)
        try:data=json.loads(r.stdout)
        except ValueError:raise RuntimeError('CONTROL_CLI_RESPONSE_NOT_JSON') from None
        return r.returncode,data
    def command(self,service,action):
        # Same installed CLI and authenticated endpoint used in normal operation.
        state=self.status();c=state['control']
        names={'pause':'pause-today','flatten':'flatten-and-pause','resume':'resume','reconcile':'reconcile'}
        extra=['--request-id',str(uuid.uuid4())]
        if action=='resume':extra+=['--next-signal','--expected-version',str(c['version']),'--session-date',c['session_date']]
        rc,data=self.cli(names[action],*extra)
        if rc:
            from market_lab.hilega_production_foundation.core import Blocked
            raise Blocked(data.get('reason','ISOLATED_CLI_COMMAND_FAILED'))
        return data

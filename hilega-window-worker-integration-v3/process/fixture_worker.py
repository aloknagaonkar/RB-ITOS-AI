"""Run exact bundled launcher with a disposable clock; no order-gate modification."""
import argparse,json,os,re,runpy,sys
from pathlib import Path
from window import need
from fixture_clock import now

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);a=p.parse_args()
    workspace=a.workspace.resolve();now(workspace)
    need(os.environ.get('HILEGA_PRODUCTION_SIM_DB')==str(workspace/'application.sqlite'),'DISPOSABLE_DATABASE_BINDING_REQUIRED')
    sys.dont_write_bytecode=True;sys.path[:0]=[str(a.bundle/'backend'),str(a.bundle/'runtime')]
    import market_lab.hilega_production_foundation.core as core
    OriginalDateTime=core.datetime
    class FixtureDateTime(OriginalDateTime):
        @classmethod
        def now(cls,tz=None):
            value=now(workspace)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    core.datetime=FixtureDateTime
    sys.argv=[str(a.bundle/'closed_worker_launcher.py'),'--watch','--env-file',str(workspace/'empty.env'),'--source',str(workspace/'strategy.jsonl')]
    diagnostics=[]
    def trace(frame,event,arg):
        if event=='exception':
            kind,value,_=arg
            if isinstance(value,Exception) and not isinstance(value,(KeyError,StopIteration,AttributeError,ImportError)):
                reason=str(value).split(':',1)[0]
                safe=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',reason) else 'DETAIL_NOT_EXPORTED'
                item=dict(error_type=kind.__name__,reason=safe,file=Path(frame.f_code.co_filename).name,line=frame.f_lineno,function=frame.f_code.co_name)
                if not diagnostics or diagnostics[-1]!=item:diagnostics.append(item)
                diagnostics[:]=diagnostics[-20:]
        return trace
    sys.settrace(trace)
    try:
        runpy.run_path(sys.argv[0],run_name='__main__')
    finally:
        sys.settrace(None)
        # No exception repr, credentials, provider bodies or authorized URLs are exported.
        (workspace/'WORKER-STARTUP-DIAGNOSTIC.json').write_text(json.dumps(dict(exception_trace=diagnostics,trace_changes_validation=False),indent=2)+'\n')
        (workspace/'WORKER-STARTUP-DIAGNOSTIC.json').chmod(0o600)

if __name__=='__main__':main()

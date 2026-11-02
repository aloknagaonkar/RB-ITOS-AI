"""Run exact bundled launcher with a disposable clock; no order-gate modification."""
import argparse,json,os,runpy,sys
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
    runpy.run_path(sys.argv[0],run_name='__main__')
if __name__=='__main__':main()

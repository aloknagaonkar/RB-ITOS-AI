"""Exact candidate CLI with a synthetic clock; only marked disposable test workspaces."""
import argparse,json,os,runpy,socket,sys
from datetime import datetime
from pathlib import Path


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--workspace',type=Path,required=True);a=ap.parse_args()
    w=a.workspace.resolve();marker=json.loads((w/'WORKER-FIXTURE.json').read_text())
    assert marker['workspace']==str(w) and marker['synthetic_only'] is True
    assert os.environ['HILEGA_PRODUCTION_SIM_DB']==marker['application_db']
    def denied(*a,**kw):raise AssertionError('Network denied in synthetic worker fixture')
    socket.socket.connect=denied;socket.create_connection=denied;socket.getaddrinfo=denied
    sys.dont_write_bytecode=True;sys.path[:0]=[str(a.bundle/'backend'),str(a.bundle/'runtime')]
    import market_lab.hilega_production_foundation.core as core
    Original=core.datetime
    class Clock(Original):
        @classmethod
        def now(cls,tz=None):
            value=datetime.fromisoformat(marker['now'])
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    core.datetime=Clock
    sys.argv=[str(a.bundle/'closed_worker_launcher.py'),'--watch','--env-file',str(w/'empty.env'),'--source',marker['journal']]
    runpy.run_path(sys.argv[0],run_name='__main__')


if __name__=='__main__':main()

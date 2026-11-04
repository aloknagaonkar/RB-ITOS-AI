"""Run one disposable process scenario; never accepts a live application database."""
import argparse,json,sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--workspace',type=Path,required=True);ap.add_argument('--scenario',choices=['fresh-signal','dead-guard-fresh-signal','guard-loss-after-plan','guard-loss-after-adapter','guard-loss-before-commit','normal-timeout','initiator-loss','managed-guard-loss'],required=True);a=ap.parse_args()
    here=Path(__file__).absolute().parent
    if a.scenario in {'fresh-signal','dead-guard-fresh-signal','guard-loss-after-plan','guard-loss-after-adapter','guard-loss-before-commit'}:
        sys.path.insert(0,str(here/'process'));from end_to_end import run
        result=run(a.bundle,a.workspace,scenario=a.scenario);result['worker_cli_signed_seed_boundary_verified']=a.scenario=='fresh-signal'
    else:
        sys.path.insert(0,str(here/'timeout'));from rehearse import run
        result=run(a.bundle,a.workspace,kill_initiator=a.scenario=='initiator-loss')
        result.update(scenario=a.scenario,initiator_sigkill_tested=a.scenario=='initiator-loss')
    (a.workspace/'SCENARIO-RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()

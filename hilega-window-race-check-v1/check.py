"""Characterize the pre-resume guard-death race on disposable state only."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
from window import need

def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)), 'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def sha(p):return hashlib.sha256(raw(p)).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--window-review',type=Path,required=True);a=ap.parse_args();root=a.repo.absolute();review=a.window_review.absolute();here=Path(__file__).absolute().parent
    for n,h in json.loads(raw(here/'MANIFEST.json')).items():need(sha(here/n)==h,'TOOL_CHANGED')
    need(review.parent==root and review.name.startswith('hilega-window-worker-review-'),'EXACT_REVIEW_REQUIRED')
    r=json.loads(raw(review/'RESULT.json'));need(r['status']=='WORKER_BOUNDARY_AND_MANAGED_WINDOW_CANDIDATE_PASS' and r['gate_overridden'] is False,'PASSED_CLOSED_CANDIDATE_REQUIRED')
    bundle=review/'candidate';need(r['candidate']==str(bundle),'EXACT_CANDIDATE_REQUIRED');need(sha(bundle/'RELEASE-MANIFEST.json')==r['candidate_release_sha256']=='a23ddba83ca884366a1007da3c3bee0edb3e356bd635b9dfcaffb192db264ce9','RELEASE_CHANGED')
    for n,h in json.loads(raw(bundle/'RELEASE-MANIFEST.json'))['files'].items():
        rel=Path(n);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_PATH_REQUIRED');need(sha(bundle/rel)==h,'CANDIDATE_CHANGED')
    out=Path(tempfile.mkdtemp(prefix='hilega-window-race-review-',dir=root));out.chmod(0o700)
    # Imported rehearsal permits only its self-created disposable marker and database paths.
    from rehearse import run
    result=run(bundle,out/'pre-resume-guard-loss',kill_initiator=False)
    result.update(status='PRE_RESUME_RACE_CHARACTERIZED_DEPLOYMENT_BLOCKED',live_apply_available=False,installed_sources_modified=False,live_controller_resumed=False,production_execution_enabled=False,production_ready=False,audit_folder=str(out))
    p=out/'RESULT.json';p.write_text(json.dumps(result,indent=2)+'\n');p.chmod(0o600);print(json.dumps(result,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps(dict(status='RACE_CHECK_REQUIRES_AUDIT_REVIEW',error_type=type(e).__name__,live_apply_available=False)));raise SystemExit(2)

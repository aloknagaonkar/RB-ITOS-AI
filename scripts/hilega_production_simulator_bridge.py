"""Approved CLOSED preparation bundle launcher; no execution factory."""
from pathlib import Path
import hashlib,json,runpy,os,sys
root=Path('/home/aloknagaonkar46/RB-ITOS-AI/data/runtime/hilega-closed-releases/e9e092399fcf29672d5273c18ef138de645a8feec573407954d1db62392d0b59')
raw=(root/"RELEASE-MANIFEST.json").read_bytes()
if hashlib.sha256(raw).hexdigest()!='e9e092399fcf29672d5273c18ef138de645a8feec573407954d1db62392d0b59':raise ValueError("CLOSED_RELEASE_MANIFEST_CHANGED")
for name,expected in json.loads(raw)["files"].items():
    rel=Path(name)
    if rel.is_absolute() or ".." in rel.parts:raise ValueError("CLOSED_RELEASE_PATH_INVALID")
    p=root/rel
    if any(q.is_symlink() for q in [p,*p.parents]) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError("CLOSED_RELEASE_INPUT_CHANGED")
identity=runpy.run_path(str(root/"rehearse.py"),run_name="closed_runtime_identity")
identity["verify_runtime_payload"](root)
sys.path[:0]=[str(root/"backend"),str(root/"runtime")]
from dotenv import dotenv_values
env_file=Path(".env")
for i,arg in enumerate(sys.argv[1:],1):
    if arg=="--env-file" and i+1<len(sys.argv):env_file=Path(sys.argv[i+1])
    elif arg.startswith("--env-file="):env_file=Path(arg.split("=",1)[1])
settings=dotenv_values(env_file) if env_file.exists() else {}
for name in ("HILEGA_DISABLED_HANDOFF_CONFIG","HILEGA_DISABLED_HANDOFF_CONFIG_SHA256","HILEGA_FACTORY_ATTACHMENT_FILE","HILEGA_FACTORY_ATTACHMENT_SHA256"):
    if name in os.environ or name in settings:raise ValueError("REGISTRATION_ACTIVATION_NOT_APPROVED_FOR_CLOSED_DEPLOYMENT")
runpy.run_path(str(root/"closed_worker_launcher.py"),run_name="__main__")

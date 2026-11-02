"""Approved CLOSED preparation bundle launcher; no execution factory."""
from pathlib import Path
import hashlib,json,runpy
root=Path('/home/aloknagaonkar46/RB-ITOS-AI/data/runtime/hilega-closed-releases/2182e0479f27f4fcbf26bf9edae6f7a14df0b9de6e6fba6ef998fcde3112e0e7')
raw=(root/"RELEASE-MANIFEST.json").read_bytes()
if hashlib.sha256(raw).hexdigest()!='2182e0479f27f4fcbf26bf9edae6f7a14df0b9de6e6fba6ef998fcde3112e0e7':raise ValueError("CLOSED_RELEASE_MANIFEST_CHANGED")
for name,expected in json.loads(raw)["files"].items():
    rel=Path(name)
    if rel.is_absolute() or ".." in rel.parts:raise ValueError("CLOSED_RELEASE_PATH_INVALID")
    p=root/rel
    if any(q.is_symlink() for q in [p,*p.parents]) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError("CLOSED_RELEASE_INPUT_CHANGED")
identity=runpy.run_path(str(root/"rehearse.py"),run_name="closed_runtime_identity")
identity["verify_runtime_payload"](root)
runpy.run_path(str(root/"closed_worker_launcher.py"),run_name="__main__")

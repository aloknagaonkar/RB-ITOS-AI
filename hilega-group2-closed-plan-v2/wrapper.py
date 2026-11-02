def wrapper(bundle,digest):
    return ('"""Approved CLOSED preparation bundle launcher; no execution factory."""\n'
        'from pathlib import Path\nimport hashlib,json,runpy\n'
        'root=Path('+repr(str(bundle))+')\n'
        'raw=(root/"RELEASE-MANIFEST.json").read_bytes()\n'
        'if hashlib.sha256(raw).hexdigest()!='+repr(digest)+':raise ValueError("CLOSED_RELEASE_MANIFEST_CHANGED")\n'
        'for name,expected in json.loads(raw)["files"].items():\n'
        '    rel=Path(name)\n'
        '    if rel.is_absolute() or ".." in rel.parts:raise ValueError("CLOSED_RELEASE_PATH_INVALID")\n'
        '    p=root/rel\n'
        '    if any(q.is_symlink() for q in [p,*p.parents]) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError("CLOSED_RELEASE_INPUT_CHANGED")\n'
        'identity=runpy.run_path(str(root/"rehearse.py"),run_name="closed_runtime_identity")\n'
        'identity["verify_runtime_payload"](root)\n'
        'runpy.run_path(str(root/"closed_worker_launcher.py"),run_name="__main__")\n').encode()

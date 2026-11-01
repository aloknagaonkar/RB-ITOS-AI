
import hashlib
from pathlib import Path
import subprocess

target = Path('/home/aloknagaonkar46/.config/systemd/user/hilega-lifecycle-reference.service')
expected = '36667fa21486256d168ef3ea4eb02494819e71e78ae1bd6f4f584ba6ff6de3a0'
name = 'hilega-lifecycle-reference.service'
if target.is_symlink() or not target.is_file():
    raise SystemExit("STOP: installed unit unavailable; inspect manually")
if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
    raise SystemExit("STOP: installed unit changed; inspect manually")
subprocess.run(["systemctl", "--user", "disable", "--now", name], check=True)
target.unlink()
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
print("Companion removed. Application databases and other services preserved.")

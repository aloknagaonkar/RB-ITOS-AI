from pathlib import Path
import hashlib, json, shutil
from datetime import datetime
root=Path.cwd()
bundle=Path(__file__).resolve().parent
expected=json.loads((bundle/'expected.json').read_text())
for rel,sha in expected.items():
 p=root/rel
 if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
  raise SystemExit('Source differs from reviewed snapshot: '+rel+'; no changes made')
backup=root/'data'/'patch-backups'/('pending-switch-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
for rel in expected:
 target=backup/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/rel,target)
env=root/'.env'
if env.exists():shutil.copy2(env,backup/'environment.backup')
for p in (bundle/'files').rglob('*'):
 if p.is_file():
  target=root/p.relative_to(bundle/'files');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
lines=env.read_text().splitlines() if env.exists() else []
lines=[line for line in lines if not line.startswith('HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=')]
lines.append('HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=1')
env.write_text('\n'.join(lines)+'\n')
print('Installed pending direction switch. Backup:',backup)
print('Restart services to load the rule.')

from pathlib import Path
import shutil, subprocess, sys
from datetime import datetime, timezone
root=Path.cwd();bundle=Path(__file__).resolve().parent
page=root/'frontend/src/hilegaMilegaShadow.tsx';component=root/'frontend/src/hilegaPcrWorkspace.tsx';dist=root/'frontend/dist'
s=page.read_text();anchor='    <HilegaExpiryWorkspace/>'
if '<HilegaPcrWorkspace/>' not in s:
    if s.count(anchor)!=1:raise SystemExit('STOP: Hilega UI anchor differs; no source changed')
    s="import HilegaPcrWorkspace from './hilegaPcrWorkspace'\n"+s.replace(anchor,anchor+'\n    <HilegaPcrWorkspace/>')
backup=root/'data/backups'/('hilega-pcr-ui-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
shutil.copy2(page,backup/page.name)
had=component.exists();had_dist=dist.exists()
if had:shutil.copy2(component,backup/component.name)
if had_dist:shutil.copytree(dist,backup/'dist')
try:
    shutil.copy2(bundle/'files/frontend/src/hilegaPcrWorkspace.tsx',component);page.write_text(s)
    subprocess.run([sys.executable,'-m','pytest','-q','tests/test_strike_positioning.py'],check=True,env={**__import__('os').environ,'PYTHONPATH':'backend:.'})
    subprocess.run(['npm','--prefix','frontend','run','build'],check=True)
except BaseException:
    shutil.copy2(backup/page.name,page)
    if had:shutil.copy2(backup/component.name,component)
    else:component.unlink(missing_ok=True)
    if dist.exists():shutil.rmtree(dist)
    if had_dist:shutil.copytree(backup/'dist',dist)
    raise
print('PASS: Hilega PCR panel installed. Collection setup is separate. Backup:',backup)

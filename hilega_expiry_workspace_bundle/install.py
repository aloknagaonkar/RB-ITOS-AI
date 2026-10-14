from pathlib import Path
import shutil,subprocess,datetime
ROOT=Path.cwd()
BUNDLE=Path(__file__).resolve().parent
main=ROOT/'frontend/src/hilegaMilegaShadow.tsx'
component=ROOT/'frontend/src/hilegaExpiryWorkspace.tsx'
if not main.is_file():raise SystemExit('Run from RB-ITOS-AI repository root')
text=main.read_text()
marker='    <HilegaUpstoxSandboxDashboard/>'
if '<HilegaExpiryWorkspace/>' not in text:
    if text.count(marker)!=1:raise SystemExit('STOP: Sandbox workspace anchor differs; source unchanged')
    text=text.replace(marker,'    <HilegaExpiryWorkspace/>\n\n'+marker)
if "from './hilegaExpiryWorkspace'" not in text:
    text="import HilegaExpiryWorkspace from './hilegaExpiryWorkspace'\n"+text
backup=ROOT/'data/backups'/('hilega-expiry-workspace-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
backup.mkdir(parents=True)
shutil.copy2(main,backup/main.name)
existed=component.exists()
if existed:shutil.copy2(component,backup/component.name)
try:
    shutil.copy2(BUNDLE/'files/frontend/src/hilegaExpiryWorkspace.tsx',component)
    main.write_text(text)
    subprocess.run(['npm','--prefix','frontend','run','build'],check=True)
    if (ROOT/'.git').exists():
        subprocess.run(['git','diff','--check'],check=True)
except Exception:
    shutil.copy2(backup/main.name,main)
    if existed:shutil.copy2(backup/component.name,component)
    else:component.unlink(missing_ok=True)
    raise SystemExit('STOP: source restored. Rebuild frontend if build output changed.')
print('PASS: expiry workspace installed. Refresh dashboard after deployment reload.')
print('Backend, expiry resolver, strategy, session arm and orders unchanged.')
print('Backup:',backup)

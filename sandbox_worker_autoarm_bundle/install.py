import argparse,ast,subprocess,shutil,os
from pathlib import Path
from datetime import datetime,timezone
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--check',action='store_true');a=p.parse_args();root=a.repo.resolve();module=root/'backend/market_lab/hilega_upstox_sandbox_basket_v2.py'
original=module.read_text();marker='from .hilega_sandbox_daily_autoarm_v1 import maybe_autoarm_in_worker'
if marker in original:
 if 'maybe_autoarm_in_worker(w,a.env_file)' not in original:raise SystemExit('Import marker present but serve hook missing; no files changed')
 updated=original
else:
 old='            try:result=w.run_once()'
 if original.count(old)!=1:raise SystemExit('Expected serve-loop anchor not unique; no files changed')
 updated=original.replace(old,'            try:\n                '+marker+'\n                maybe_autoarm_in_worker(w,a.env_file)\n                result=w.run_once()',1)
helper=Path(__file__).with_name('hilega_sandbox_daily_autoarm_v1.py');helpertext=helper.read_text();ast.parse(helpertext);ast.parse(updated)
cron=None
if shutil.which('crontab'):
 result=subprocess.run(['crontab','-l'],capture_output=True,text=True)
 if result.returncode not in (0,1) or (result.returncode==1 and result.stderr and 'no crontab' not in result.stderr.lower()):raise SystemExit('Cannot safely inspect managed cron entry; no files changed')
 start='# BEGIN HILEGA_SANDBOX_DAILY_AUTOARM';end='# END HILEGA_SANDBOX_DAILY_AUTOARM';keep=[];inside=False;count=0
 for line in result.stdout.splitlines():
  if line==start:
   if inside:raise SystemExit('Malformed managed cron block')
   inside=True;count+=1;continue
  if line==end:
   if not inside:raise SystemExit('Malformed managed cron block')
   inside=False;continue
  if not inside:keep.append(line)
 if inside or count>1:raise SystemExit('Malformed managed cron block')
 if count:cron=(result.stdout,'\n'.join(keep)+'\n')
print('Validated: worker-integrated daily arming; managed cron removal='+str(cron is not None))
if a.check:raise SystemExit(0)
backup=root/'backups'/('sandbox-worker-autoarm-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True);shutil.copy2(module,backup/module.name)
target=module.with_name(helper.name)
if target.exists():shutil.copy2(target,backup/target.name)
for path,text in [(target,helpertext),(module,updated)]:
 tmp=path.with_name(path.name+'.autoarm.tmp');tmp.write_text(text);os.replace(tmp,path)
if cron:
 (backup/'crontab-before.txt').write_text(cron[0]);os.chmod(backup/'crontab-before.txt',0o600)
 subprocess.run(['crontab','-'],input=cron[1],text=True,check=True)
print('APPLIED; backup:',backup)
print('Restart only the Sandbox worker using its existing stop/start scripts.')

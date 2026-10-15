"""Daily premarket Sandbox auto-arming. Uses existing reconciliation guards."""
import argparse,json,os,sys,subprocess
from pathlib import Path
from datetime import datetime,time
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
EXPECTED='HILEGA_V2_ALIGNMENT_DUAL_EXIT'

def decide(now,control,status,active_strategy,expected_strategy=EXPECTED,disabled_days=()):
 now=now.astimezone(IST);day=now.date().isoformat()
 if now.weekday()>=5 or day in disabled_days:return 'SKIP_NON_TRADING_DATE'
 if active_strategy!=expected_strategy or control.get('strategy_id')!=active_strategy:return 'BLOCKED_STRATEGY_MISMATCH'
 if control.get('live_execution_enabled') or not control.get('sandbox_only'):return 'BLOCKED_NOT_SANDBOX_ONLY'
 if control.get('kill_switch'):return 'BLOCKED_MANUAL_KILL_SWITCH'
 if control.get('entries_blocked'):return 'BLOCKED_RECONCILIATION_REQUIRED'
 if status.get('open_legs',0):return 'BLOCKED_OPEN_LEGS'
 if status.get('uncertain_requests',0):return 'BLOCKED_UNCERTAIN_REQUESTS'
 if control.get('armed') and control.get('session_date')==day:return 'ALREADY_ARMED_TODAY'
 if not time(8,45)<=now.time().replace(tzinfo=None)<time(9,15):return 'SKIP_OUTSIDE_PREMARKET_WINDOW'
 return 'ARM_TODAY'

def process(now,adapter,apply=False,expected_strategy=EXPECTED,disabled_days=()):
 control=adapter.control();status=adapter.status();active=adapter.active_strategy()
 action=decide(now,control,status,active,expected_strategy,disabled_days)
 result=dict(status=action,session_date=now.astimezone(IST).date().isoformat(),active_strategy_id=active,armed_session_date=control.get('session_date'),worker_running=adapter.running(),open_legs=status.get('open_legs',0),uncertain_requests=status.get('uncertain_requests',0),sandbox_only=True,live_execution_enabled=False,changed=False)
 if action not in ('ARM_TODAY','ALREADY_ARMED_TODAY'):return result
 adapter.assert_config_ready()
 # Existing arm() verifies basket, legacy dispatch/journal and audit chain.
 if action=='ARM_TODAY' and apply:
  adapter.arm(now.astimezone(IST).date());result.update(status='ARMED_TODAY',armed_session_date=result['session_date'],changed=True)
 if apply and not adapter.running():adapter.start_worker();result['worker_running']=adapter.running()
 if apply and not result['worker_running']:raise RuntimeError('SANDBOX_WORKER_NOT_RUNNING_AFTER_START')
 return result

class RepoAdapter:
 def __init__(self,root,env):
  sys.path.insert(0,str(root/'backend'))
  from market_lab import hilega_upstox_sandbox_basket_v2 as basket
  self.basket=basket;self.worker=basket.BasketWorker(env=env);self.root=root;self.env=env
 def control(self):return self.worker.control.read()
 def status(self):return self.worker.status()
 def active_strategy(self):return self.basket.strategy(self.env)
 def assert_config_ready(self):self.basket.SandboxConfig.from_env(self.env).assert_ready('SANDBOX_ONLY')
 def arm(self,day):
  self.basket.arm(day,Path(os.getenv('HILEGA_SANDBOX_BRIDGE_SOURCE',str(self.basket.DEFAULT_SOURCE))),self.worker.control,self.worker.store,self.env)
 def running(self):
  path=self.root/self.basket.DEFAULT_PID
  try:
   pid=int(path.read_text().strip());os.kill(pid,0)
   return b'market_lab.hilega_upstox_sandbox_basket_v2' in Path('/proc',str(pid),'cmdline').read_bytes()
  except (OSError,ValueError):return False
 def start_worker(self):subprocess.run(['bash',str(self.root/'scripts/start_hilega_upstox_sandbox_worker.sh')],check=True,capture_output=True,text=True,timeout=20)

def main():
 p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--expected-strategy',default=EXPECTED)
 mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true');mode.add_argument('--scheduled',action='store_true')
 a=p.parse_args();root=a.repo.resolve();now=datetime.now(IST)
 # Cron can run in any server timezone: action window and weekday use IST.
 if a.scheduled and (now.weekday()>=5 or not time(9,0)<=now.time().replace(tzinfo=None)<time(9,15)):return
 os.chdir(root);status_path=root/'data/live-observation/hilega-upstox-sandbox-v2/auto-arm-status.json'
 try:
  disabled_path=root/'data/live-observation/hilega-upstox-sandbox-v2/auto-arm-disabled-dates.json'
  disabled=json.loads(disabled_path.read_text()) if disabled_path.exists() else []
  if not isinstance(disabled,list) or not all(isinstance(d,str) for d in disabled):raise ValueError('INVALID_DISABLED_DATE_LIST')
  adapter=RepoAdapter(root,root/'.env')
  from filelock import FileLock
  # Same lock as run_once(): worker cannot submit while reconciliation and arming run.
  with FileLock(str(adapter.worker.store.path)+'.worker.lock',timeout=20):
   # Worker startup is nonblocking; its run_once waits until this lock is released.
   result=process(now,adapter,apply=a.apply or a.scheduled,expected_strategy=a.expected_strategy,disabled_days=disabled)
  result['timestamp']=now.isoformat()
 except Exception as exc:
  result=dict(status='AUTO_ARM_FAILED',error_type=type(exc).__name__,timestamp=now.isoformat(),sandbox_only=True,live_execution_enabled=False)
  # Known guard messages are safe; no arbitrary exception bodies or tokens are logged.
  known=['OPEN_OR_UNCERTAIN_SANDBOX_LEGS_RECONCILE_BEFORE_REARM','LEGACY_SANDBOX_POSITION_OR_FAILURE_REQUIRES_RECONCILIATION','LEGACY_UNCERTAIN_REQUEST_RECONCILE_BEFORE_SWITCH','SANDBOX_WORKER_NOT_RUNNING_AFTER_START','HILEGA_UPSTOX_SANDBOX_ENABLED is not 1','sandbox kill switch is active','V1 permits exactly one lot','max orders per session must be positive','analytics and sandbox tokens are required']
  if str(exc) in known:result['reason']=str(exc)
 status_path.parent.mkdir(parents=True,exist_ok=True);tmp=status_path.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2)+'\n');os.replace(tmp,status_path)
 print(json.dumps(result,indent=2))
 if result['status'].startswith(('BLOCKED','AUTO_ARM_FAILED')):raise SystemExit(1)


def maybe_autoarm_in_worker(worker,env,lock_factory=None):
 """Called by serve loop, not order submission. At most one attempt per5m bucket."""
 now=datetime.now(IST)
 if now.weekday()>=5 or not time(9,0)<=now.time().replace(tzinfo=None)<time(9,15):return None
 root=Path.cwd();path=root/'data/live-observation/hilega-upstox-sandbox-v2/auto-arm-status.json'
 bucket=now.hour*12+now.minute//5;day=now.date().isoformat()
 if lock_factory is None:
  from filelock import FileLock
  lock_factory=FileLock
 try:
  with lock_factory(str(worker.store.path)+'.worker.lock',timeout=2):
   previous=json.loads(path.read_text()) if path.exists() else {}
   if previous.get('worker_attempt_day')==day and previous.get('worker_attempt_bucket')==bucket:return None
   disabled_path=root/'data/live-observation/hilega-upstox-sandbox-v2/auto-arm-disabled-dates.json'
   disabled=json.loads(disabled_path.read_text()) if disabled_path.exists() else []
   if not isinstance(disabled,list) or not all(isinstance(d,str) for d in disabled):raise ValueError('INVALID_DISABLED_DATE_LIST')
   class ExistingWorkerAdapter(RepoAdapter):
    def __init__(self):
     from . import hilega_upstox_sandbox_basket_v2 as basket
     self.basket=basket;self.worker=worker;self.root=root;self.env=Path(env)
    def running(self):return True
    def start_worker(self):raise RuntimeError('Existing worker must not spawn itself')
   result=process(now,ExistingWorkerAdapter(),apply=True,disabled_days=disabled)
 except Exception as exc:
  result=dict(status='AUTO_ARM_FAILED',error_type=type(exc).__name__,sandbox_only=True,live_execution_enabled=False)
  safe=['OPEN_OR_UNCERTAIN_SANDBOX_LEGS_RECONCILE_BEFORE_REARM','LEGACY_SANDBOX_POSITION_OR_FAILURE_REQUIRES_RECONCILIATION','LEGACY_UNCERTAIN_REQUEST_RECONCILE_BEFORE_SWITCH','HILEGA_UPSTOX_SANDBOX_ENABLED is not 1','sandbox kill switch is active','analytics and sandbox tokens are required']
  if str(exc) in safe:result['reason']=str(exc)
 result.update(timestamp=now.isoformat(),worker_attempt_day=day,worker_attempt_bucket=bucket,scheduler='SANDBOX_WORKER')
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.worker-autoarm.tmp');tmp.write_text(json.dumps(result,indent=2)+'\n');os.replace(tmp,path)
 print(json.dumps({'sandbox_autoarm':result}),flush=True)
 return result

if __name__=='__main__':main()

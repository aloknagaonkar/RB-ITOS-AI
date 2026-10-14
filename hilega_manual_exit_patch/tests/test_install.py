import ast,importlib.util,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('manual_installer',HERE/'install.py');installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
REPO=HERE.parent/'source/RB-ITOS-AI-feature-pcr-foundation'
if not REPO.exists():REPO=Path.cwd()
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  for p in ['backend/market_lab/hilega_upstox_sandbox_basket_v2.py','backend/market_lab/hilega_alignment_dual_exit_live_v1.py','backend/market_lab/api.py','frontend/src/hilegaUpstoxSandboxDashboard.tsx']:
   target=self.root/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(REPO/p,target)
 def changes(self):
  with patch.object(installer,'ROOT',self.root):return installer.changes()
 def test_supported_source_generates_eight_files(self):
  result=self.changes();self.assertEqual(len(result),8)
  for p,s in result.items():
   if p.suffix=='.py':ast.parse(s)
  worker=result[Path('backend/market_lab/hilega_upstox_sandbox_basket_v2.py')]
  self.assertIn('service_manual_exit(self)',worker);self.assertIn('SKIPPED_MANUAL_EXIT',worker)
  live=result[Path('backend/market_lab/hilega_alignment_dual_exit_live_v1.py')];self.assertIn('if manual_block:self.gate.pending.clear()',live);self.assertIn('after_bootstrap(self,now)',live)
 def test_unknown_version_aborts_without_writes(self):
  p=self.root/'backend/market_lab/hilega_upstox_sandbox_basket_v2.py';p.write_text(p.read_text().replace('    def close(self):self.analytics.close();self.sandbox.close()','    def close(self): pass'))
  before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  with self.assertRaisesRegex(ValueError,'supported anchor'):self.changes()
  self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
 def test_no_double_install(self):
  result=self.changes()
  for p,t in result.items():target=self.root/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(t)
  with self.assertRaisesRegex(ValueError,'already present'):self.changes()
 def test_sandbox_transport_never_reads_live_client(self):
  worker=self.changes()[Path('backend/market_lab/hilega_upstox_sandbox_basket_v2.py')];tree=ast.parse(worker);klass=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='BasketTransport');methods=[x for x in klass.body if isinstance(x,ast.FunctionDef) and x.name in {'order_details','cancel_order'}]
  definition=ast.ClassDef(name='Transport',bases=[],keywords=[],body=methods,decorator_list=[]);module=ast.fix_missing_locations(ast.Module(body=[definition],type_ignores=[]));scope={};exec(compile(module,'transport','exec'),scope)
  calls=[]
  class Client:
   def get(self,url,params):calls.append(('GET',url,params));return {'data':{'order_id':'A'}}
   def delete(self,url,params):calls.append(('DELETE',url,params));return {'data':{'order_id':'A'}}
  tr=scope['Transport']();tr.sandbox=Client();tr._body=lambda x:x;tr.analytics=None
  self.assertEqual(tr.order_details(order_id='A')['order_id'],'A');tr.order_details(tag='HILM_X');tr.cancel_order('A');self.assertEqual([x[1] for x in calls],['/v2/order/details','/v2/order/details','/v3/order/cancel'])
if __name__=='__main__':unittest.main()

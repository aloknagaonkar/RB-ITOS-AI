import ast,copy,importlib.util,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pnl_installer',HERE/'install.py');install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)
helper=HERE/'files/backend/market_lab/hilega_manual_exit_pnl_v1.py';spec=importlib.util.spec_from_file_location('manual_pnl',helper);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
BASE=HERE.parent/'source/RB-ITOS-AI-feature-pcr-foundation'
if not BASE.exists():BASE=Path.cwd()
class Tests(unittest.TestCase):
 def setUp(self):
  self.entry=dict(quantity=65,observed_option_price=199.8)
  self.leg=dict(quantity=65,entry_price=199.8,exit_price=None,exit_time='13:48',points=None,pnl_rupees=None,status='SELL_ACKNOWLEDGED',exit_order_id='NO_FILLED_BUY')
  self.ex=dict(manual_exit_confirmed=True,event_timestamp='2026-10-14T14:43:00+05:30',confirmed_buy=dict(terminal=True,filled=0,average_price=0),confirmed_exit_price=None,confirmed_pnl_rupees=0)
 def test_zero_filled_cancel_has_zero_pnl_no_fake_sell(self):
  r=mod.apply_manual_exit_pnl(self.leg,self.entry,self.ex);self.assertEqual(r['pnl_rupees'],0);self.assertEqual(r['quantity'],0);self.assertEqual(r['requested_quantity'],65);self.assertEqual(r['status'],'CANCELLED_UNFILLED');self.assertIsNone(r['exit_order_id']);self.assertIsNone(r['points'])
 def test_exit_time_uses_closure_event_not_entry_timestamp(self):
  self.ex['timestamp']='2026-10-14T13:48:00+05:30';self.assertEqual(mod.apply_manual_exit_pnl(self.leg,self.entry,self.ex)['exit_time'],'2026-10-14T14:43:00+05:30')
 def test_confirmed_fill_prices_replace_estimated_quote(self):
  self.ex.update(confirmed_buy=dict(terminal=True,filled=65,average_price=200),confirmed_exit_price=205,confirmed_pnl_rupees=325)
  r=mod.apply_manual_exit_pnl(self.leg,self.entry,self.ex);self.assertEqual(r['entry_price'],200);self.assertEqual(r['exit_price'],205);self.assertEqual(r['points'],5);self.assertEqual(r['pnl_rupees'],325);self.assertEqual(r['status'],'SELL_FILLED')
 def test_partial_buy_only_filled_quantity_used(self):
  self.ex.update(confirmed_buy=dict(terminal=True,filled=25,average_price=200),confirmed_exit_price=198,confirmed_pnl_rupees=-50)
  r=mod.apply_manual_exit_pnl(self.leg,self.entry,self.ex);self.assertEqual(r['quantity'],25);self.assertEqual(r['pnl_rupees'],-50)
 def test_missing_evidence_not_reported_as_zero(self):
  self.ex.pop('confirmed_pnl_rupees');r=mod.apply_manual_exit_pnl(self.leg,self.entry,self.ex);self.assertIsNone(r['pnl_rupees']);self.assertEqual(r['status'],'MANUAL_EXIT_EVIDENCE_INCOMPLETE')
 def test_automatic_exit_projection_unchanged(self):
  original=copy.deepcopy(self.leg);self.ex.pop('manual_exit_confirmed');self.assertEqual(mod.apply_manual_exit_pnl(self.leg,self.entry,self.ex),original)
 def test_missing_fill_price_not_fabricated(self):
  self.ex.update(confirmed_buy=dict(terminal=True,filled=65,average_price=200),confirmed_exit_price=None,confirmed_pnl_rupees=325);r=mod.apply_manual_exit_pnl(self.leg,self.entry,self.ex);self.assertIsNone(r['pnl_rupees'])
 def fixture(self,root):
  # Generate exactly the already-installed manual patch state, then apply this fix.
  for p in ['backend/market_lab/hilega_directional_candle_ui_v1.py','backend/market_lab/hilega_historical_ui_api_v1.py','frontend/src/hilegaDecisionTable.tsx']:
   f=root/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_text((BASE/p).read_text())
  if 'service_manual_exit' in (BASE/'backend/market_lab/hilega_upstox_sandbox_basket_v2.py').read_text():
   for p in ['backend/market_lab/hilega_manual_exit_v1.py','backend/market_lab/hilega_upstox_sandbox_basket_v2.py','frontend/src/hilegaUpstoxSandboxDashboard.tsx']:
    f=root/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_text((BASE/p).read_text())
   return
  spec=importlib.util.spec_from_file_location('base_installer',HERE.parent/'hilega_manual_exit_patch/install.py');mi=importlib.util.module_from_spec(spec);spec.loader.exec_module(mi);mi.ROOT=BASE
  for p,t in mi.changes().items():
   f=root/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(t)
 def test_installer_compatible_with_installed_manual_patch(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.fixture(root);prior=install.ROOT;install.ROOT=root
   try:
    result=install.changes();self.assertEqual(len(result),8)
    for p,t in result.items():
     if p.suffix=='.py':ast.parse(t)
    self.assertIn('timestamp=stamp(worker)',result[Path('backend/market_lab/hilega_manual_exit_v1.py')])
   finally:install.ROOT=prior
 def test_dashboard_cancelled_basket_is_closed_with_zero_pnl(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.fixture(root);prior=install.ROOT;install.ROOT=root
   try:result=install.changes()
   finally:install.ROOT=prior
   tree=ast.parse(result[Path('backend/market_lab/hilega_upstox_sandbox_basket_v2.py')]);f=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='build_dashboard')
   # Replace its single local helper import with the real tested helper in scope.
   f.body=[x for x in f.body] # body contains helper import inside loop; AST walk transform.
   class Imports(ast.NodeTransformer):
    def visit_ImportFrom(self,node):return ast.Pass() if node.module=='hilega_manual_exit_pnl_v1' else node
   f=Imports().visit(f)
   contract=dict(role=0,strike=22650,option_type='CE',instrument_key='K0',lot_size=65,expiry='2026-10-19')
   en=dict(trade_id='T',direction='BULLISH',role=0,event_type='ENTRY',contract=contract,quantity=65,observed_option_price=199.8,timestamp='2026-10-14T13:48:34+05:30',event_timestamp='2026-10-14T13:48:00+05:30',broker_order_id='BUY',session_date='2026-10-14',strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT')
   ex=dict(en,event_type='EXIT',broker_order_id='NO_FILLED_BUY',observed_option_price=None,**self.ex)
   store=SimpleNamespace(accepted=lambda:[en,ex],rows=lambda:[],uncertain=lambda:[],path=root/'journal')
   worker=SimpleNamespace(store=store,control=SimpleNamespace(read=lambda:dict(session_date='2026-10-14',strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT')),status=lambda:{})
   scope=dict(Path=Path,MODEL='HILEGA_UPSTOX_SANDBOX_BASKET_V2',BasketWorker=lambda **k:worker,now=lambda:datetime.fromisoformat('2026-10-14T14:44:00+05:30'),strategy=lambda env:'HILEGA_V2_ALIGNMENT_DUAL_EXIT',SandboxConfig=SimpleNamespace(from_env=lambda env:SimpleNamespace(analytics_token='',lots=1)),DEFAULT_PID=root/'no-pid',JOURNAL=root/'journal',os=__import__('os'),apply_manual_exit_pnl=mod.apply_manual_exit_pnl)
   exec(compile(ast.fix_missing_locations(ast.Module(body=[f],type_ignores=[])),'patched_dashboard','exec'),scope)
   data=scope['build_dashboard']();self.assertFalse(data['active_trades']);self.assertEqual(data['completed_trades'][0]['status'],'CANCELLED_UNFILLED');self.assertEqual(data['completed_trades'][0]['missing_pnl_legs'],0);self.assertEqual(data['pnl']['missing_pnl_legs'],0);self.assertEqual(data['pnl']['closed_estimated_rupees'],0)
if __name__=='__main__':unittest.main()

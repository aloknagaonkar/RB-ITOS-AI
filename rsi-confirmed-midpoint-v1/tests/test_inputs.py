import unittest,tempfile,json,sys
from pathlib import Path
from datetime import date
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).parents[1]))
from inputs import resolve_sessions
from monthly_report import requested_days
class InputTests(unittest.TestCase):
 def fake(self,root):
  prior=date(2026,9,30)
  def read(path,day):
   if Path(path).read_text()!='valid':raise ValueError('invalid')
   return ['rows']
  def save(path,day,rows):
   path.mkdir(parents=True,exist_ok=True);p=path/(str(day)+'.json');p.write_text('valid');return p
  return SimpleNamespace(required_sessions=lambda day:[prior],read_session=read,save_session=save,fetch_session=lambda source,day:['recovered'])
 def test_recovery_preserves_original_bad_bytes_and_exports_valid(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);bad=root/'bad.json';bad.write_text('corrupt');day=date(2026,10,1);prior=date(2026,9,30);w=self.fake(root);idx={str(prior):bad};cache=root/'research'
   recovered=resolve_sessions(w,idx,day,source=object(),cache_root=cache,export_inputs=True)
   self.assertEqual(recovered,[str(prior),str(day)]);self.assertEqual(bad.read_text(),'corrupt')
   self.assertTrue(all(p.parent==cache for p in idx.values()))
 def test_missing_without_recovery_fails(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   with self.assertRaisesRegex(ValueError,'MISSING_OR_INVALID'):
    resolve_sessions(self.fake(root),{},date(2026,10,1),source=None,cache_root=root/'research',export_inputs=True)
 def test_valid_export_copies_without_fetch(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);w=self.fake(root);p=root/'original.json';p.write_text('valid');idx={'2026-09-30':p,'2026-10-01':p}
   w.fetch_session=lambda *args:(_ for _ in ()).throw(AssertionError('unexpected fetch'))
   self.assertEqual(resolve_sessions(w,idx,date(2026,10,1),source=None,cache_root=root/'research',export_inputs=True),[])
   self.assertEqual(p.read_text(),'valid')
 def test_october_scope_complete(self):
  ds=requested_days(None,'2026-10','2026-10-31',date(2026,11,24));self.assertEqual(len(ds),31);self.assertEqual(ds[0],'2026-10-01');self.assertEqual(ds[-1],'2026-10-31')
if __name__=='__main__':unittest.main()

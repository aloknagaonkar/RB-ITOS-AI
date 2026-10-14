"""Regression for VM's regular market_lab package before patch installation."""
import os,subprocess,sys,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
REPO=Path.cwd()/'backend/market_lab'
if not REPO.exists():REPO=HERE.parent/'source/RB-ITOS-AI-feature-pcr-foundation/backend/market_lab'
class PackageLoadingTests(unittest.TestCase):
 def test_uninstalled_patch_loads_with_regular_repo_package(self):
  with tempfile.TemporaryDirectory() as tmp:
   package=Path(tmp)/'market_lab';package.mkdir()
   (package/'__init__.py').write_text('__path__.append('+repr(str(REPO))+')\n')
   env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join([tmp,str(HERE/'tests')])
   code='import test_manual_exit; import market_lab; assert market_lab.__file__.endswith("__init__.py"); assert "hilega_manual_exit_patch/files" in test_manual_exit.m.__file__'
   r=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stderr)
if __name__=='__main__':unittest.main()

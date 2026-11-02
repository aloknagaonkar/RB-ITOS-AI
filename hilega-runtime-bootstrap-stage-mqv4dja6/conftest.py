import os,sys,runpy
from pathlib import Path
stage=Path(os.environ['HILEGA_EXCLUSIVE_TEST_STAGE']).resolve()
name='closed_application_coordinator_v1'
if name in sys.modules:
    assert Path(sys.modules[name].__file__).resolve()==stage/'closed_application_coordinator_v1.py'
else:
    runpy.run_path('/home/aloknagaonkar46/RB-ITOS-AI/hilega-exclusive-route-v1/conftest.py')

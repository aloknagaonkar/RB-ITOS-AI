"""Load staged modules only inside the VM pytest subprocess; never installed files."""
import importlib.util
import os
from pathlib import Path
import sys

stage=os.environ.get('HILEGA_EXCLUSIVE_TEST_STAGE')
if not stage:raise RuntimeError('Use the package runner: isolated staged imports required')
stage=Path(stage).resolve()
import market_lab
market_lab.__path__=[str(stage/'backend/market_lab'),*list(market_lab.__path__)]
import market_lab.hilega_preparation_runtime_v1 as preparation


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

preparation.source=load('market_lab.hilega_preparation_runtime_v1.source',
    stage/'backend/market_lab/hilega_preparation_runtime_v1/source.py')
load('closed_application_coordinator_v1',stage/'closed_application_coordinator_v1.py')

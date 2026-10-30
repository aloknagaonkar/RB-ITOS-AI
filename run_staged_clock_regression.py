"""Run existing preparation tests with the staged Source in memory."""
import hashlib
import importlib.util
from pathlib import Path
import sys

root = Path.cwd().resolve()
sys.path[:0] = [str(root / "backend"), str(root / "tests")]

candidate = root / "hilega-entry-clock-stage-a6h90flu/source.py"
installed = root / "backend/market_lab/hilega_preparation_runtime_v1/source.py"
expected = {
    candidate: "8163ca0db32a5fc95358368d2f474a6f0e083c853cb97008b7574f1241310f71",
    installed: "c792ebb12ab5d17a20d624843c8f6a2af7b8405fd69439d68c283a2ee1bb1a5b",
}

for path, fingerprint in expected.items():
    if path.is_symlink() or not path.is_file():
        raise SystemExit("STOP: regular source required")
    if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
        raise SystemExit("STOP: source fingerprint changed")

import market_lab.hilega_preparation_runtime_v1 as package

name = "market_lab.hilega_preparation_runtime_v1.source"
spec = importlib.util.spec_from_file_location(name, candidate)
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
setattr(package, "source", module)

import pytest

result = pytest.main([
    "-q",
    "tests/test_hilega_atomic_disabled_binding_v1.py",
    "tests/test_hilega_application_preparation_v1.py",
    "tests/test_hilega_preparation_wait_admission_v1.py",
    "tests/test_hilega_preparation_pricing_wiring_v1.py",
    "tests/test_hilega_limit_candidate_v1.py",
    "tests/test_hilega_consolidated_adapter_v1.py",
    "hilega-entry-reservation-integration-tools-v1/test_runtime_reservation.py",
])

if hashlib.sha256(installed.read_bytes()).hexdigest() != expected[installed]:
    raise SystemExit("STOP: installed source changed during tests")
print("Installed Source unchanged; staged regression exit code:", result)
raise SystemExit(result)
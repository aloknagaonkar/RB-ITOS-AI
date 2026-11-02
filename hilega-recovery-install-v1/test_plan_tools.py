import pytest
from plan_tools import unit,dropin,exact_files,quote

def test_unit_runs_isolated_python():assert b'"-I" "-B"' in unit('/python','/script','/config','abc')
def test_dependency_is_required_and_ordered():assert b'Requires=hilega-closed-pause-recovery.service' in dropin() and b'After=' in dropin()
def test_specifiers_rejected():
    with pytest.raises(ValueError):quote('/tmp/%u')
def test_newline_rejected():
    with pytest.raises(ValueError):quote('/tmp/x\ny')
def test_existing_install_is_not_silently_overwritten():
    with pytest.raises(ValueError):exact_files([dict(destination='/tmp/target',old_sha256='old')])
def test_duplicate_target_rejected():
    with pytest.raises(ValueError):exact_files([dict(destination='/tmp/target',old_sha256=None)]*2)

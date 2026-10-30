"""Review-time clock checks; installed Source, synthetic temporary fixtures."""
from copy import deepcopy
from datetime import timezone
import importlib.util
from pathlib import Path

import pytest

from test_hilega_application_preparation_v1 import env, process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources

# Reuse only the synthetic time-shift helper.
# Its staged-source fixture is not imported or activated.
from test_staged_entry_clock import move

path = Path(__file__).resolve().parent / "dispatch_precondition_review.py"
spec = importlib.util.spec_from_file_location("clock_review_target", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("case", [
    "before_open", "open_session", "late_session", "at_close",
])
@pytest.mark.parametrize("use_utc", [False, True])
def test_review_clock_boundary(bound_env, case, use_utc):
    e = bound_env
    hour, minute = (9, 15) if case in {
        "before_open", "open_session"
    } else (14, 50)
    signal = move(e, hour, minute)
    from test_hilega_application_preparation_v1 import append, BULL
    append(e["path"], [BULL], at=signal.isoformat())
    e["source"].run_source_once(e["path"])
    assert len(e["adapter_store"].requests()) == 1
    source = read_sources(
        e["store"].path, e["adapter_store"].path, PIN["scope"])

    at = e["clock"][0]
    if case == "before_open":
        at = signal.replace(hour=9, minute=14, second=59)
    elif case == "at_close":
        at = signal.replace(hour=14, minute=55, second=0)
    if use_utc:
        at = at.astimezone(timezone.utc)

    original = deepcopy(source)
    result = module.review(source, PIN, as_of=at.isoformat())

    if case in {"before_open", "at_close"}:
        assert result["reference_checks_passed"] is False, result
        assert result["reasons"] == ["ENTRY_CLOCK_WINDOW_CLOSED"], result
    else:
        assert result["reference_checks_passed"] is True, result

    assert source == original
    for flag in (
        "entry_permission", "orders_sent", "production_execution_enabled",
        "reservation_release_permission", "production_ready",
    ):
        assert result[flag] is False

    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0
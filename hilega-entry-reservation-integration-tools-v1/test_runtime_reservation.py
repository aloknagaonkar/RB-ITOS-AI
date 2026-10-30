"""VM-only tests against the patched real Source using existing temporary fixtures."""
import json
import pytest
from test_hilega_application_preparation_v1 import env,process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row


def rows(env):
    with env["store"].db() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_cash_reservations'").fetchone()
        return [json.loads(r[0]) for r in db.execute(
            "SELECT data FROM preparation_cash_reservations")] if exists else []


def test_actual_source_reserves_with_disabled_request(bound_env):
    process(bound_env)
    reservation,=rows(bound_env)
    request,=bound_env["adapter_store"].requests()
    verify_row(reservation,PIN)
    assert reservation["id"]==request["request_id"]
    assert reservation["held_cents"]==660000
    assert reservation["amount_cents"]<=reservation["cash_cap_cents"]
    assert reservation["policy"]["daily_loss_limit_paise"] is None
    assert reservation["policy"]["daily_loss_limit_required"] is False
    assert reservation["broker_cash_locked"] is False
    assert reservation["production_execution_enabled"] is False
    assert bound_env["store"].control()["mode"]=="PAUSED"


@pytest.mark.parametrize("point",["AFTER_ADAPTER_REQUEST_INSERT","BEFORE_COMMIT"])
def test_actual_source_rolls_back_reservation_and_request(bound_env,point):
    class Interrupted(BaseException):pass
    def interrupt(at):
        if at==point:raise Interrupted()
    bound_env["source"].checkpoint=interrupt
    with pytest.raises(Interrupted):process(bound_env)
    assert rows(bound_env)==[]
    assert bound_env["adapter_store"].requests()==[]


def test_source_replay_does_not_duplicate_local_reservation(bound_env):
    process(bound_env)
    before=rows(bound_env)
    bound_env["source"].run_source_once(bound_env["path"])
    assert rows(bound_env)==before
    assert len(before)==1

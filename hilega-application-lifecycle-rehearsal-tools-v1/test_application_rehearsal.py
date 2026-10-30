"""VM-only application rehearsal. Fixture control is separate from running services."""
from copy import deepcopy
from unittest.mock import Mock,patch
import pytest
from application_rehearsal import Rehearsal
from test_hilega_application_preparation_v1 import env,process,command
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from signature_checks import sign


@pytest.fixture(autouse=True)
def explicit_fixture_scope(monkeypatch):
    # The shared test PIN is synthetic. No real pin or live capture is loaded.
    monkeypatch.setitem(PIN,"scope","FIXTURE:APPLICATION-LIFECYCLE-REHEARSAL")
    from market_lab.hilega_production_broker_observation_v1 import Client
    monkeypatch.setattr(Client,"get",lambda *a,**k:pytest.fail("Unexpected broker read"))


@pytest.fixture
def rehearsal(bound_env,tmp_path):
    process(bound_env)
    return Rehearsal(bound_env,PIN,tmp_path)


def test_actual_application_entry_to_fixture_exit_and_gross(rehearsal):
    r=rehearsal
    assert r.reservation["policy"]["daily_loss_limit_required"] is False
    assert r.reservation["policy"]["allocation_numerator"]==1
    assert r.reservation["policy"]["allocation_denominator"]==2
    r.entry_fill();r.prepare_exit();r.submit_exit();r.acknowledge_exit()
    r.fill_exit(r.quantity)
    result=r.reconcile()
    assert result["remaining_quantity"]==0
    assert result["fixture_flat_reference_verified"] is True
    assert result["reservation_release_permission"] is False
    gross=r.gross()
    assert gross["gross_realized_paise"]==r.quantity*100
    assert gross["realized_net_pnl_paise"] is None
    assert gross["fees_complete"] is False
    assert r.application_retained()


def test_partial_cancel_retains_application_hold(rehearsal):
    r=rehearsal
    r.entry_fill();r.prepare_exit();r.submit_exit();r.acknowledge_exit()
    partial=r.quantity//2
    r.fill_exit(partial)
    first=r.reconcile()
    assert first["remaining_quantity"]==r.quantity-partial
    r.adapter.cancel(r.exit_id)
    result=r.reconcile(offset=15)
    assert result["all_referenced_orders_terminal"] is True
    assert result["fixture_flat_reference_verified"] is False
    assert r.application_retained()


def test_lost_exit_response_is_not_resubmitted(rehearsal):
    r=rehearsal
    r.entry_fill();r.prepare_exit()
    r.submit_exit(timeout_after=True)
    before=len(r.adapter.transport.orders())
    with pytest.raises(ValueError,match="EXIT_ACKNOWLEDGEMENT_UNRESOLVED_NO_RETRY"):
        r.acknowledge_exit()
    with patch.object(r.adapter.transport,"send",side_effect=AssertionError("No retry")):
        repeated=r.adapter.submit(r.exit_id)
    assert repeated["idempotent_replay"] is True
    assert len(r.adapter.transport.orders())==before
    assert r.application_retained()


def test_external_order_is_not_adopted(rehearsal):
    r=rehearsal
    r.entry_fill();r.prepare_exit();r.submit_exit();r.acknowledge_exit()
    r.fill_exit(r.quantity)
    snapshot=r.capture(offset=11,include_exit=True)
    extra=deepcopy(snapshot["orders"][0])
    extra.update(order_id="FIXTURE-UNRELATED",filled=0,pending=0,status="CANCELLED")
    snapshot["orders"].append(extra)
    snapshot.pop("signature");snapshot["signature"]=sign(snapshot,r.pin)
    with pytest.raises(ValueError,match="MISSING_OR_UNLINKED_ACCOUNT_ORDER"):
        r.reconcile(snapshot=snapshot)
    assert r.application_retained()


def test_deployed_source_restart_does_not_duplicate_entry(rehearsal):
    r=rehearsal
    from market_lab.hilega_production_foundation.core import Store,SimBroker,Service
    from market_lab.hilega_preparation_runtime_v1.source import Source
    store=Store(r.app)
    service=Service(store,SimBroker(store),lambda:r.env["clock"][0])
    source=Source(service,run_id="synthetic-lease",
                  provider=lambda:pytest.fail("Committed source must not recollect"))
    source.run_source_once(r.env["path"])
    assert len(r.env["adapter_store"].requests())==1
    assert r.application_retained()


def test_manual_live_exit_still_blocked_on_preparation_route(rehearsal):
    from market_lab.hilega_production_foundation.core import Blocked
    with pytest.raises(Blocked,match="LIVE_EXIT_NOT_IMPLEMENTED"):
        command(rehearsal.env["s"],"flatten")
    assert rehearsal.application_retained()

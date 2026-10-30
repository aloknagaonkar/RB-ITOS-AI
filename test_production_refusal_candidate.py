"""Production-scoped candidate, tested only on synthetic temporary DBs."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest

import production_application_closed_decision as candidate
from test_hilega_application_preparation_v1 import env, process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN

STAGE = Path("hilega-refusal-persistence-stage-k2aygu9h")
PINS = {
    "production_closed_decisions.py":
        "ac3d7415693bc13e5e17d15602db8cab94ccb3718e7749b1ad90b21efc6a5802",
    "production_application_closed_decision.py":
        "261f4f8f2fd3707311681036a6f54ce6fa218c85c9ef0bc50ff606963258b11a",
    "closed_entry_dispatch.py":
        "51db070f229fafc6fc12b7a8e294dd476903fa151f847f937330746128fc6412",
    "dispatch_precondition_review.py":
        "92cd3dad83eadfaf5158c092842eb707556749cfd609ae4968dd65ac2625e990",
}
TABLE = "preparation_closed_dispatch_decisions"


@pytest.fixture(autouse=True)
def verify_candidate():
    for name, expected in PINS.items():
        path = STAGE / name
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    assert Path(candidate.__file__).resolve() == (
        STAGE / "production_application_closed_decision.py").resolve()


@pytest.fixture
def prepared(bound_env, tmp_path):
    e = bound_env
    assert e["store"].path.resolve().parent == tmp_path.resolve()
    assert e["adapter_store"].path.resolve().parent == tmp_path.resolve()
    # PIN comes from test fixtures; no private pin is loaded.
    assert PIN["scope"] == "UPSTOX:" + "b" * 64
    process(e)
    return e


def invoke(e, *, pin=None, checkpoint=lambda stage: None):
    return candidate.record_fixture_decision(
        e["store"], e["adapter_store"].path,
        PIN if pin is None else pin,
        clock=lambda: e["clock"][0],
        checkpoint=checkpoint,
    )


def rows(e):
    with e["store"].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)
        ).fetchone()
        return db.execute(
            "SELECT id,data FROM " + TABLE + " ORDER BY id"
        ).fetchall() if exists else []


def preparation(e):
    with e["store"].db() as db:
        return {
            table: db.execute(
                "SELECT * FROM " + table + " ORDER BY rowid").fetchall()
            for table in (
                "preparation_plans", "preparation_shadow_holds",
                "preparation_outbox", "preparation_cash_reservations",
            )
        }


def test_commit_replay_preserves_preparation(prepared):
    e = prepared
    before = preparation(e)
    broker = e["adapter_store"].path.read_bytes()
    first = invoke(e)
    saved = rows(e)
    second = invoke(e)
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert len(saved) == 1 and rows(e) == saved
    assert preparation(e) == before
    assert e["adapter_store"].path.read_bytes() == broker
    value = json.loads(saved[0][1])
    assert value["account_scope"] == PIN["scope"]
    assert value["production_execution_enabled"] is False
    assert value["report"]["reference_checks_passed"] is True


@pytest.mark.parametrize("point", [
    "AFTER_REVIEW", "AFTER_DECISION_INSERT", "BEFORE_COMMIT",
])
def test_interruption_rolls_back(prepared, point):
    e = prepared
    before = preparation(e)

    class Interrupted(BaseException):
        pass

    def checkpoint(stage):
        if stage == point:
            raise Interrupted()

    with pytest.raises(Interrupted):
        invoke(e, checkpoint=checkpoint)
    assert rows(e) == []
    assert preparation(e) == before


def test_wrong_account_rejected_before_persistence(prepared):
    e = prepared
    with pytest.raises(ValueError, match="ADAPTER_PIN_SCOPE_OR_MODE_MISMATCH"):
        invoke(e, pin=dict(PIN, scope="UPSTOX:" + "a" * 64))
    assert rows(e) == []


def test_fixture_scope_rejected(prepared):
    e = prepared
    with pytest.raises(ValueError, match="^PINNED_UPSTOX_SCOPE_REQUIRED$"):
        invoke(e, pin=dict(PIN, scope="FIXTURE:OTHER"))
    assert rows(e) == []


def test_expiry_before_commit_rolls_back(prepared):
    e = prepared

    def checkpoint(stage):
        if stage == "BEFORE_COMMIT":
            e["clock"][0] += timedelta(seconds=61)

    with pytest.raises(ValueError, match="^REVIEW_CHANGED_BEFORE_COMMIT$"):
        invoke(e, checkpoint=checkpoint)
    assert rows(e) == []


def test_persisted_signature_tampering_is_not_overwritten(prepared):
    e = prepared
    invoke(e)
    key, raw = rows(e)[0]
    value = json.loads(raw)
    value["report"]["reference_checks_passed"] = False
    with e["store"].db() as db:
        db.execute(
            "UPDATE " + TABLE + " SET data=? WHERE id=?",
            (json.dumps(value), key),
        )
    tampered = rows(e)
    with pytest.raises(ValueError, match="^PERSISTED_DECISION_SIGNATURE_INVALID$"):
        invoke(e)
    assert rows(e) == tampered
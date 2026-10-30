"""Verified/uncertain outcomes on synthetic temporary application DBs."""
from unittest.mock import patch

import pytest

import refusal_decision_readback as readback
import refusal_record_operations as operations
from test_production_refusal_candidate import (
    prepared, verify_candidate, env, bound_env, rows,
)
from hilega_application_preparation_fixtures import PIN


def invoke(e, tmp_path):
    return operations.execute_record(
        e["store"], e["adapter_store"].path,
        pin_reader=lambda: dict(PIN), clock=lambda: e["clock"][0],
        backup_root=tmp_path / "backups",
    )


def test_success_authenticates_exact_returned_id(prepared, tmp_path):
    e = prepared
    original = readback.inspect
    ids = []

    def inspector(*args, **kwargs):
        ids.append(kwargs["decision_id"])
        return original(*args, **kwargs)

    with patch.object(readback, "inspect", inspector):
        result = invoke(e, tmp_path)
    assert ids == [result["decision_id"]]
    assert result["exact_decision_signature_verified"] is True
    assert result["persistence_outcome"] == "VERIFIED_COMMITTED_REFUSAL"
    assert result["orders_sent"] is False


def test_readback_failure_remains_unknown(prepared, tmp_path):
    e = prepared
    with patch.object(
        readback, "inspect",
        side_effect=ValueError("SYNTHETIC_READBACK_FAILURE"),
    ):
        result = invoke(e, tmp_path)
    assert len(rows(e)) == 1
    assert result["persistence_outcome"] == "UNKNOWN_REVIEW_REQUIRED"
    assert result["database_modified"] is None
    assert result["automatic_write_retry"] is False
    assert "exact_decision_signature_verified" not in result


def test_wrong_returned_id_is_not_reported_verified(prepared, tmp_path):
    e = prepared
    original = operations.guarded_record

    def wrong_id(*args, **kwargs):
        result = original(*args, **kwargs)
        result["decision_id"] = "0" * 64
        return result

    with patch.object(operations, "guarded_record", wrong_id):
        result = invoke(e, tmp_path)
    assert len(rows(e)) == 1
    assert result["reason"] == "EXACT_DECISION_READBACK_MISSING"
    assert result["persistence_outcome"] == "UNKNOWN_REVIEW_REQUIRED"
    assert result["automatic_write_retry"] is False
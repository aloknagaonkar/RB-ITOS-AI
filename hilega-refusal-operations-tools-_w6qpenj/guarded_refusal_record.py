"""Operational guard candidate. No broker transport or order authority."""
from copy import deepcopy
import re

from production_application_closed_decision import record_application_decision
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def guarded_record(store, adapter, *, pin_reader, clock, backup, checkpoint=lambda s: None):
    pin = deepcopy(pin_reader())
    need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
         "PINNED_UPSTOX_SCOPE_REQUIRED")
    source = read_sources(store.path, adapter, pin["scope"])
    need(pin_reader() == pin, "ACCOUNT_PIN_CHANGED_DURING_PREFLIGHT")

    if not source["requests"]:
        return dict(
            status="NO_PREPARED_REQUEST_NO_WRITE",
            database_modified=False,
            orders_sent=False,
            production_execution_enabled=False,
            reservation_release_permission=False,
        )

    need(len(source["requests"]) == 1, "SINGLE_REQUEST_REQUIRED")
    # Backup implementation is supplied by the eventual CLI/runtime adapter.
    # It must finish successfully before any recorder transaction begins.
    backup_result = backup()
    need(backup_result is not None, "BACKUP_REQUIRED")
    need(pin_reader() == pin, "ACCOUNT_PIN_CHANGED_BEFORE_WRITE")

    def guarded_checkpoint(stage):
        checkpoint(stage)
        need(pin_reader() == pin, "ACCOUNT_PIN_CHANGED_DURING_TRANSACTION")

    result = record_application_decision(
        store, adapter, pin, clock=clock,
        checkpoint=guarded_checkpoint,
    )
    return dict(
        result,
        database_modified=not result["idempotent_replay"],
        backup_completed=True,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
    )
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_lab.domain import PCRConfig
from market_lab.pcr_expiry_rollover_v1 import (
    ensure_current_pcr_expiry,
)
from market_lab.storage import (
    Configuration,
    Control,
    active_config,
    initialize,
    make_engine,
)


TODAY = date(2026, 9, 26)


def engine_with_config(
    tmp_path,
    *,
    expiry=date(2026, 9, 22),
    enabled=True,
):
    engine = make_engine(
        f"sqlite:///{tmp_path / 'lab.db'}"
    )
    initialize(engine)

    with Session(engine) as session, session.begin():
        control = session.get(Control, 1)
        row = session.get(
            Configuration,
            control.active_config_id,
        )

        config = PCRConfig(
            provider="upstox",
            underlying="NSE_INDEX|Nifty 50",
            expiry=expiry,
            wings=5,
            anchor_time="09:20",
            interval_seconds=15,
        )

        row.payload = config.model_dump(mode="json")
        control.enabled = enabled

    return engine


def test_nonexpired_config_does_not_call_resolver(tmp_path):
    engine = engine_with_config(
        tmp_path,
        expiry=date(2026, 9, 29),
    )

    def resolver(*args, **kwargs):
        raise AssertionError("resolver must not run")

    result = ensure_current_pcr_expiry(
        engine,
        today=TODAY,
        resolver=resolver,
    )

    assert result["status"] == "CURRENT"
    assert result["expiry"] == "2026-09-29"


def test_expired_config_rolls_to_new_immutable_config(tmp_path):
    engine = engine_with_config(tmp_path)

    with Session(engine) as session:
        old_id, old_config, enabled = active_config(session)

    result = ensure_current_pcr_expiry(
        engine,
        today=TODAY,
        resolver=lambda underlying, *, today: date(
            2026, 9, 29
        ),
    )

    assert result["status"] == "ROLLED_OVER"
    assert result["previous_config_id"] == old_id
    assert result["expiry"] == "2026-09-29"
    assert result["enabled"] is True
    assert result["created_config"] is True

    with Session(engine) as session:
        new_id, new_config, enabled = active_config(session)

        assert new_id != old_id
        assert new_config.expiry == date(2026, 9, 29)
        assert enabled is True

        old_row = session.get(Configuration, old_id)
        old_config_after = PCRConfig.model_validate(
            old_row.payload
        )

        assert old_config_after.expiry == date(
            2026, 9, 22
        )


def test_rollover_does_not_create_duplicate_target(tmp_path):
    engine = engine_with_config(tmp_path)

    resolver = lambda underlying, *, today: date(
        2026, 9, 29
    )

    first = ensure_current_pcr_expiry(
        engine,
        today=TODAY,
        resolver=resolver,
    )

    with Session(engine) as session, session.begin():
        # Re-point to the original expired configuration to simulate
        # a repeated rollover attempt.
        control = session.get(Control, 1)
        control.active_config_id = first[
            "previous_config_id"
        ]

    second = ensure_current_pcr_expiry(
        engine,
        today=TODAY,
        resolver=resolver,
    )

    assert second["status"] == "ROLLED_OVER"
    assert second["created_config"] is False
    assert second["config_id"] == first["config_id"]

    with Session(engine) as session:
        count = session.scalar(
            select(func.count())
            .select_from(Configuration)
        )

    assert count == 2


def test_resolver_failure_leaves_active_config_unchanged(
    tmp_path,
):
    engine = engine_with_config(tmp_path)

    with Session(engine) as session:
        old_id, old_config, enabled = active_config(session)

    def resolver(*args, **kwargs):
        raise ValueError(
            "NO_VALID_NIFTY_OPTION_EXPIRY"
        )

    with pytest.raises(
        ValueError,
        match="NO_VALID_NIFTY_OPTION_EXPIRY",
    ):
        ensure_current_pcr_expiry(
            engine,
            today=TODAY,
            resolver=resolver,
        )

    with Session(engine) as session:
        config_id, config, enabled = active_config(session)

    assert config_id == old_id
    assert config.expiry == old_config.expiry
    assert enabled is True

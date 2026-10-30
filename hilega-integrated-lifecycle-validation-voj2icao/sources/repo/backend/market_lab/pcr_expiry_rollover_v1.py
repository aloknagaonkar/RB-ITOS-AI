"""Automatic immutable expiry rollover for the live PCR collector."""

from __future__ import annotations

import os
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import IST, PCRConfig
from .storage import (
    Configuration,
    Control,
    active_config,
    utc_now,
)
from .upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1


MODEL = "PCR_EXPIRY_ROLLOVER_V1"


def _resolve_expiry(
    config: PCRConfig,
    *,
    today: date,
    resolver=None,
) -> date:
    if resolver is not None:
        return resolver(
            config.underlying,
            today=today,
        )

    source = UpstoxLiveShadowSourcesV1(
        os.getenv("UPSTOX_ACCESS_TOKEN", "")
    )
    try:
        return source.resolve_option_expiry(
            config.underlying,
            today=today,
        )
    finally:
        source.close()


def ensure_current_pcr_expiry(
    engine,
    *,
    today: date | None = None,
    resolver=None,
) -> dict:
    """
    Ensure the active live-PCR configuration uses a non-expired expiry.

    Old Configuration rows are immutable.  When rollover is required,
    either an identical existing target configuration is reused or a new
    Configuration row is created and Control.active_config_id is switched.

    Control.enabled is never changed.
    """
    today = today or datetime.now(IST).date()

    with Session(engine) as session:
        config_id, config, enabled = active_config(session)

    if config.provider != "upstox":
        return {
            "model": MODEL,
            "status": "NOT_APPLICABLE",
            "config_id": config_id,
            "enabled": enabled,
            "expiry": config.expiry.isoformat(),
            "expiry_source": "CONFIGURED",
        }

    if config.expiry >= today:
        return {
            "model": MODEL,
            "status": "CURRENT",
            "config_id": config_id,
            "enabled": enabled,
            "expiry": config.expiry.isoformat(),
            "expiry_source": "CONFIGURED",
        }

    resolved_expiry = _resolve_expiry(
        config,
        today=today,
        resolver=resolver,
    )

    if resolved_expiry < today:
        raise ValueError("RESOLVED_PCR_EXPIRY_IS_EXPIRED")

    new_payload = config.model_dump(mode="json")
    new_payload["expiry"] = resolved_expiry.isoformat()

    with Session(engine) as session, session.begin():
        control = session.get(Control, 1)
        if control is None:
            raise ValueError("PCR_CONTROL_ROW_MISSING")

        current_row = session.get(
            Configuration,
            control.active_config_id,
        )
        if current_row is None:
            raise ValueError("PCR_ACTIVE_CONFIGURATION_MISSING")

        current_config = PCRConfig.model_validate(
            current_row.payload
        )

        # Another actor may have changed configuration while the provider
        # expiry lookup was running.  Never overwrite that decision.
        if current_row.id != config_id:
            return {
                "model": MODEL,
                "status": "CONFIG_CHANGED_DURING_RESOLUTION",
                "config_id": current_row.id,
                "enabled": control.enabled,
                "expiry": current_config.expiry.isoformat(),
                "expiry_source": "CONFIGURED",
            }

        # Avoid creating duplicate immutable config versions when an exact
        # target configuration already exists.
        target = None
        rows = session.scalars(
            select(Configuration)
            .order_by(Configuration.id.desc())
        ).all()

        for row in rows:
            if row.payload == new_payload:
                target = row
                break

        created = False

        if target is None:
            target = Configuration(
                created_at=utc_now(),
                payload=new_payload,
            )
            session.add(target)
            session.flush()
            created = True

        previous_config_id = control.active_config_id
        previous_expiry = current_config.expiry.isoformat()

        control.active_config_id = target.id

        return {
            "model": MODEL,
            "status": "ROLLED_OVER",
            "previous_config_id": previous_config_id,
            "config_id": target.id,
            "enabled": control.enabled,
            "previous_expiry": previous_expiry,
            "expiry": resolved_expiry.isoformat(),
            "expiry_source": "AUTO_UPSTOX_INSTRUMENT_SEARCH",
            "created_config": created,
        }

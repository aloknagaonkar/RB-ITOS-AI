"""Run one independent collector: python -m market_lab.worker."""

import logging
import os
import time
from datetime import datetime, time as local_time, timedelta

from filelock import FileLock, Timeout
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain import IST, Snapshot, in_session
from .gateways import DemoGateway, GatewayError, UpstoxGateway
from .storage import Observation, active_config, initialize, make_engine, record, update_health

logger = logging.getLogger(__name__)


def demo_next(engine, config_id, config):
    with Session(engine) as session:
        previous = session.scalar(
            select(Observation)
            .where(Observation.config_id == config_id)
            .order_by(Observation.id.desc())
            .limit(1)
        )
        step = session.scalar(
            select(func.count()).select_from(Observation).where(Observation.config_id == config_id)
        )
    if previous:
        at = Snapshot.model_validate(previous.snapshot).received_at.astimezone(IST) + timedelta(minutes=1)
        if at.time() >= local_time(15, 30):
            at = datetime.combine(
                at.date() + timedelta(days=1), local_time.fromisoformat(config.anchor_time), IST
            )
    else:
        at = datetime.combine(datetime.now(IST).date(), local_time.fromisoformat(config.anchor_time), IST)
    while at.weekday() >= 5:
        at += timedelta(days=1)
    return DemoGateway().collect_at(config, at, step)


def run():
    engine = make_engine()
    initialize(engine)
    # All supported processes run from project root. Distributed workers require DB leases later.
    with FileLock("data/collector.lock", timeout=0):
        gateway = None
        gateway_config_id = None
        next_due = 0.0
        failures = 0
        last_config = None
        try:
            while True:
                with Session(engine) as session:
                    config_id, config, enabled = active_config(session)
                if config_id != last_config:
                    failures, next_due, last_config = 0, 0.0, config_id
                    update_health(
                        engine,
                        state="configuration_changed",
                        config_id=config_id,
                        failures=0,
                        last_error=None,
                        last_success_at=None,
                        last_observation_id=None,
                    )
                if not enabled:
                    update_health(engine, state="paused", config_id=config_id, failures=failures)
                    time.sleep(1)
                    continue
                if config.provider == "upstox" and not in_session(datetime.now(IST)):
                    update_health(engine, state="outside_session", config_id=config_id)
                    time.sleep(1)
                    continue
                if time.monotonic() < next_due:
                    update_health(engine, config_id=config_id)
                    time.sleep(1)
                    continue
                update_health(engine, state="collecting", config_id=config_id)
                try:
                    if config.provider == "demo":
                        snapshot = demo_next(engine, config_id, config)
                    else:
                        if gateway is None or gateway_config_id != config_id:
                            if gateway:
                                gateway.close()
                            gateway = UpstoxGateway(os.getenv("UPSTOX_ACCESS_TOKEN", ""))
                            gateway_config_id = config_id
                        snapshot = gateway.collect(config)
                    observation_id = record(engine, config_id, snapshot)
                    failures = 0
                    update_health(
                        engine,
                        state="receiving",
                        config_id=config_id,
                        failures=0,
                        last_error=None,
                        last_success_at=datetime.now(IST).isoformat(),
                        last_observation_id=observation_id,
                    )
                except (GatewayError, ValueError) as exc:
                    failures += 1
                    # Validation errors are deliberately sanitized; raw provider payloads stay out of logs.
                    reason = str(exc) if isinstance(exc, GatewayError) else "Observation validation failed."
                    update_health(
                        engine, state="backoff", config_id=config_id, failures=failures, last_error=reason
                    )
                interval = 5 if config.provider == "demo" else config.interval_seconds
                next_due = time.monotonic() + (
                    max(interval, min(300, 30 * 2 ** min(failures - 1, 4))) if failures else interval
                )
        finally:
            if gateway:
                gateway.close()
            update_health(engine, state="stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run()
    except Timeout:
        raise SystemExit("A collector already holds data/collector.lock.")
    except KeyboardInterrupt:
        pass

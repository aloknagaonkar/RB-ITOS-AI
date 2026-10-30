
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from filelock import FileLock, Timeout
from sqlalchemy.orm import Session

from .domain import IST
from .oi_vwap_causal_runtime_v1 import evaluate_checkpoint, publish_runtime_health
from .paper_production_storage_v1 import PaperControl, ensure_paper_schema, update_paper_health
from .storage import active_config, Observation, make_engine
from sqlalchemy import select
from .upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1

logger = logging.getLogger(__name__)
SERVICE_LOCK = Path("data/oi-vwap-causal-runtime.lock")


def _checkpoint_key(received_at: str) -> str:
    ts = datetime.fromisoformat(received_at.replace("Z", "+00:00")).astimezone(IST)
    minute = ts.minute - (ts.minute % 5)
    return ts.replace(minute=minute, second=0, microsecond=0).isoformat()


def _authoritative_control(session: Session) -> dict:
    row = session.get(PaperControl, 1)
    return {
        "paper_enabled": bool(row.enabled) if row else False,
        "live_execution_enabled": False,
        "max_open_positions": int(row.max_open_positions) if row else 4,
    }


def run(poll_seconds: int = 2) -> None:
    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    engine = make_engine()
    ensure_paper_schema(engine)
    SERVICE_LOCK.parent.mkdir(parents=True, exist_ok=True)

    try:
        lock = FileLock(str(SERVICE_LOCK), timeout=0)
        lock.acquire()
    except Timeout:
        raise SystemExit("Another causal runtime service is already running.")

    gateway = UpstoxLiveFuturesGatewayV1(token)
    last_checkpoint_key = None

    try:
        update_paper_health(
            engine,
            state="runtime_starting",
            paper_entry_integration=False,
            live_execution_enabled=False,
        )

        while True:
            with Session(engine) as session:
                config_id, config, collection_enabled = active_config(session)
                latest = session.scalar(
                    select(Observation)
                    .where(Observation.config_id == config_id)
                    .order_by(Observation.id.desc())
                    .limit(1)
                )
                control = _authoritative_control(session)

            if not collection_enabled or latest is None:
                update_paper_health(
                    engine,
                    state="waiting_for_market_data",
                    collection_enabled=collection_enabled,
                    **control,
                )
                time.sleep(poll_seconds)
                continue

            checkpoint_key = _checkpoint_key(latest.snapshot["received_at"])

            if checkpoint_key == last_checkpoint_key:
                update_paper_health(
                    engine,
                    state="runtime_idle",
                    latest_seen_observation_id=latest.id,
                    latest_checkpoint_key=checkpoint_key,
                    **control,
                )
                time.sleep(poll_seconds)
                continue

            decision = evaluate_checkpoint(
                engine,
                config_id=config_id,
                observation_id=latest.id,
                futures_gateway=gateway,
                now=datetime.now(IST),
            )
            publish_runtime_health(engine, decision)

            with Session(engine) as session:
                control = _authoritative_control(session)

            update_paper_health(
                engine,
                latest_checkpoint_key=checkpoint_key,
                **control,
            )

            last_checkpoint_key = checkpoint_key
            time.sleep(poll_seconds)

    finally:
        gateway.close()
        update_paper_health(
            engine,
            state="runtime_stopped",
            live_execution_enabled=False,
        )
        try:
            lock.release()
        except Exception:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run()
    except KeyboardInterrupt:
        pass

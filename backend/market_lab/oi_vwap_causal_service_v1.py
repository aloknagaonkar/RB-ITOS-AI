
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import IST
from .oi_vwap_causal_runtime_v1 import evaluate_checkpoint, publish_runtime_health
from .paper_production_storage_v1 import ensure_paper_schema, update_paper_health
from .storage import Control, Observation, active_config, make_engine
from .upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1

logger = logging.getLogger(__name__)


def run(poll_seconds: int = 2) -> None:
    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    engine = make_engine()
    ensure_paper_schema(engine)
    gateway = UpstoxLiveFuturesGatewayV1(token)

    last_processed_observation_id = None
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

            if not collection_enabled or latest is None:
                update_paper_health(
                    engine,
                    state="waiting_for_market_data",
                    collection_enabled=collection_enabled,
                    live_execution_enabled=False,
                )
                time.sleep(poll_seconds)
                continue

            if latest.id == last_processed_observation_id:
                update_paper_health(
                    engine,
                    state="runtime_idle",
                    latest_seen_observation_id=latest.id,
                    live_execution_enabled=False,
                )
                time.sleep(poll_seconds)
                continue

            # Process each new observation once. The feature builder itself chooses
            # the causal 5m checkpoint row; repeated intra-5m observations are
            # idempotent at the persisted signal/event layer.
            decision = evaluate_checkpoint(
                engine,
                config_id=config_id,
                observation_id=latest.id,
                futures_gateway=gateway,
                now=datetime.now(IST),
            )
            publish_runtime_health(engine, decision)
            last_processed_observation_id = latest.id
            time.sleep(poll_seconds)

    finally:
        gateway.close()
        update_paper_health(
            engine,
            state="runtime_stopped",
            live_execution_enabled=False,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run()
    except KeyboardInterrupt:
        pass

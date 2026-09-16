
from __future__ import annotations

"""
Drop-in service loop for P2C.1.

Key production fixes:
- one evaluation per completed 5-minute checkpoint, not every 15-second sample
- paper_enabled in health is always read from authoritative paper_control
- baseline-unavailable is surfaced as a distinct blocked state
"""

import logging
import os
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from .domain import IST
from .oi_vwap_causal_runtime_v1 import evaluate_checkpoint, publish_runtime_health
from .oi_vwap_runtime_guards_v1 import (
    authoritative_paper_control,
    latest_observation_checkpoint_key,
)
from .paper_production_storage_v1 import ensure_paper_schema, update_paper_health
from .storage import active_config, make_engine
from .upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1

logger = logging.getLogger(__name__)


def run(poll_seconds: int = 2) -> None:
    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    engine = make_engine()
    ensure_paper_schema(engine)
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
                latest = latest_observation_checkpoint_key(session, config_id=config_id)
                control = authoritative_paper_control(session)

            if not collection_enabled or latest is None:
                update_paper_health(
                    engine,
                    state="waiting_for_market_data",
                    collection_enabled=collection_enabled,
                    **control,
                )
                time.sleep(poll_seconds)
                continue

            observation_id, checkpoint_key = latest

            # One strategy decision per 5-minute checkpoint.
            if checkpoint_key == last_checkpoint_key:
                update_paper_health(
                    engine,
                    state="runtime_idle",
                    latest_seen_observation_id=observation_id,
                    latest_checkpoint_key=checkpoint_key,
                    **control,
                )
                time.sleep(poll_seconds)
                continue

            decision = evaluate_checkpoint(
                engine,
                config_id=config_id,
                observation_id=observation_id,
                futures_gateway=gateway,
                now=datetime.now(IST),
            )
            publish_runtime_health(engine, decision)

            # Refresh authoritative control values after decision health merge.
            with Session(engine) as session:
                control = authoritative_paper_control(session)
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run()
    except KeyboardInterrupt:
        pass

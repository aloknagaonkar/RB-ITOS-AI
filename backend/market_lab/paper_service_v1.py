
from __future__ import annotations

import logging
import time
from pathlib import Path

from filelock import FileLock, Timeout
from sqlalchemy.orm import Session

from .paper_production_storage_v1 import (
    LIVE_TRADING_ENABLED,
    ensure_paper_schema,
    get_paper_control,
    list_open_positions,
    update_paper_health,
)
from .storage import make_engine

logger = logging.getLogger(__name__)

SERVICE_LOCK = Path("data/paper-service.lock")


def run() -> None:
    """
    Browser-independent production paper service foundation.

    V1 foundation deliberately performs NO strategy evaluation and NO broker execution.
    It proves process independence, persistent control/state, singleton enforcement,
    DB recovery, health heartbeat, and open-position recovery.
    """
    engine = make_engine()
    ensure_paper_schema(engine)
    SERVICE_LOCK.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(str(SERVICE_LOCK), timeout=0):
        update_paper_health(engine, state="starting", recovered_open_positions=0)

        with Session(engine) as session:
            recovered = len(list_open_positions(session))

        update_paper_health(
            engine,
            state="ready",
            recovered_open_positions=recovered,
            message="Paper production foundation ready. Strategy input integration not enabled yet.",
        )

        try:
            while True:
                with Session(engine) as session:
                    control = get_paper_control(session)
                    open_positions = len(list_open_positions(session))

                state = "enabled_waiting_for_strategy_integration" if control["enabled"] else "disabled"
                update_paper_health(
                    engine,
                    state=state,
                    open_positions=open_positions,
                    max_open_positions=control["max_open_positions"],
                    paper_enabled=control["enabled"],
                    live_execution_enabled=False,
                )
                time.sleep(1)
        finally:
            update_paper_health(engine, state="stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run()
    except Timeout:
        raise SystemExit("A paper service already holds data/paper-service.lock.")
    except KeyboardInterrupt:
        pass

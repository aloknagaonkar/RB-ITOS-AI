"""Process entry point used by the local platform control script."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def write_pid(service: str) -> None:
    runtime_dir = Path("data/runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process = {
        "service": service,
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
        "project_root": str(Path.cwd().resolve()),
    }
    (runtime_dir / f"{service}.json").write_text(json.dumps(process, indent=2), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"api", "worker"}:
        raise SystemExit("Usage: python -m market_lab.runtime api|worker")
    service = sys.argv[1]
    write_pid(service)
    if service == "worker":
        from .worker import run

        run()
        return

    import uvicorn

    uvicorn.run("market_lab.api:app", host="127.0.0.1", port=8123, log_level="info")


if __name__ == "__main__":
    main()

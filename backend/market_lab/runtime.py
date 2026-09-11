"""Process entry point used by the local platform control script."""

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime
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


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None


def _historical_validate(arguments) -> None:
    from dotenv import load_dotenv

    from .gateways import GatewayError, UpstoxGateway
    from .historical_validation import validate_historical_session

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    gateway = None
    try:
        gateway = UpstoxGateway(os.getenv("UPSTOX_ACCESS_TOKEN", ""))
        report = validate_historical_session(
            gateway,
            arguments.underlying,
            arguments.session_date,
            arguments.expiry,
            arguments.wings,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    except (GatewayError, ValueError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "underlying": arguments.underlying,
            "session_date": arguments.session_date.isoformat(),
            "expiry": arguments.expiry.isoformat(),
            "wings": arguments.wings,
            "provenance": "HISTORICAL_CANDLE_RECONSTRUCTION",
            "issues": [str(error)],
        }, indent=2))
    finally:
        if gateway is not None:
            gateway.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m market_lab.runtime")
    subparsers = parser.add_subparsers(dest="service", required=True)
    subparsers.add_parser("api")
    subparsers.add_parser("worker")
    historical = subparsers.add_parser("historical-validate")
    historical.add_argument("--underlying", required=True)
    historical.add_argument("--session-date", required=True, type=_date)
    historical.add_argument("--expiry", required=True, type=_date)
    historical.add_argument("--wings", required=True, type=int)
    arguments = parser.parse_args()

    if arguments.service == "historical-validate":
        _historical_validate(arguments)
        return

    write_pid(arguments.service)
    if arguments.service == "worker":
        from .worker import run

        run()
        return

    import uvicorn

    uvicorn.run("market_lab.api:app", host="0.0.0.0", port=8123, log_level="info")

if __name__ == "__main__":
    main()

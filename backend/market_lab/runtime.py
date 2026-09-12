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



def _historical_batch(arguments) -> None:
    from dotenv import load_dotenv

    from .gateways import GatewayError, UpstoxGateway
    from .historical_batch import (
        HistoricalBatchSessionResult,
        build_historical_batch_report,
        load_historical_batch_manifest,
    )
    from .historical_validation import validate_historical_session

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    manifest = load_historical_batch_manifest(arguments.manifest)
    gateway = None
    results = []
    try:
        gateway = UpstoxGateway(os.getenv("UPSTOX_ACCESS_TOKEN", ""))
        for spec in sorted(manifest.sessions, key=lambda item: item.session_date):
            try:
                report = validate_historical_session(
                    gateway,
                    arguments.underlying,
                    spec.session_date,
                    spec.expiry,
                    arguments.wings,
                )
                results.append(HistoricalBatchSessionResult(
                    session_date=spec.session_date,
                    expiry=spec.expiry,
                    status=report.status,
                    report=report,
                    issues=report.issues,
                ))
            except (GatewayError, ValueError) as error:
                results.append(HistoricalBatchSessionResult(
                    session_date=spec.session_date,
                    expiry=spec.expiry,
                    status="UNAVAILABLE",
                    issues=[str(error)],
                ))

        batch = build_historical_batch_report(arguments.underlying, arguments.wings, results)
        rendered = json.dumps(batch.model_dump(mode="json"), indent=2)
        if arguments.output:
            output = Path(arguments.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    finally:
        if gateway is not None:
            gateway.close()



def _historical_evidence(arguments) -> None:
    from dotenv import load_dotenv

    from .gateways import GatewayError, UpstoxGateway
    from .historical_batch import load_historical_batch_manifest
    from .historical_cache import HistoricalSessionCache, HistoricalSessionCacheKey
    from .historical_evidence import (
        HistoricalEvidenceSessionSummary,
        build_historical_evidence_dataset,
        write_historical_evidence_csv,
        write_historical_evidence_json,
    )
    from .historical_research import build_historical_research_session

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    manifest = load_historical_batch_manifest(arguments.manifest)
    cache = HistoricalSessionCache(arguments.cache_dir)
    gateway = None
    sessions = []
    unavailable = []
    cache_hits = 0
    cache_misses = 0
    provider_fetches = 0
    cache_writes = 0
    try:
        for spec in sorted(manifest.sessions, key=lambda item: item.session_date):
            key = HistoricalSessionCacheKey(
                underlying=arguments.underlying,
                session_date=spec.session_date,
                expiry=spec.expiry,
                wings=arguments.wings,
            )
            session = None
            if not arguments.refresh:
                try:
                    session = cache.load(key)
                except (OSError, ValueError, json.JSONDecodeError):
                    session = None
            if session is not None:
                cache_hits += 1
                sessions.append(session)
                continue

            cache_misses += 1
            try:
                if gateway is None:
                    gateway = UpstoxGateway(os.getenv("UPSTOX_ACCESS_TOKEN", ""))
                provider_fetches += 1
                session = build_historical_research_session(
                    gateway,
                    arguments.underlying,
                    spec.session_date,
                    spec.expiry,
                    arguments.wings,
                )
                if session.status == "AVAILABLE":
                    cache.store(key, session)
                    cache_writes += 1
                    sessions.append(session)
                else:
                    unavailable.append(HistoricalEvidenceSessionSummary(
                        session_date=spec.session_date,
                        expiry=spec.expiry,
                        status="UNAVAILABLE",
                        issues=session.issues,
                    ))
            except (GatewayError, ValueError, OSError) as error:
                unavailable.append(HistoricalEvidenceSessionSummary(
                    session_date=spec.session_date,
                    expiry=spec.expiry,
                    status="UNAVAILABLE",
                    issues=[str(error)],
                ))

        dataset = build_historical_evidence_dataset(
            arguments.underlying, sessions, unavailable
        )
        if arguments.output:
            write_historical_evidence_json(dataset, arguments.output)
        if arguments.csv_output:
            write_historical_evidence_csv(dataset, arguments.csv_output)
        summary = {
            "status": dataset.status,
            "underlying": dataset.underlying,
            "requested_session_count": dataset.requested_session_count,
            "available_session_count": dataset.available_session_count,
            "unavailable_session_count": dataset.unavailable_session_count,
            "row_count": dataset.row_count,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "provider_fetches": provider_fetches,
            "cache_writes": cache_writes,
            "cache_dir": arguments.cache_dir,
            "refresh": bool(arguments.refresh),
            "provenance": dataset.provenance,
            "output": arguments.output,
            "csv_output": arguments.csv_output,
        }
        print(json.dumps(summary, indent=2))
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
    batch = subparsers.add_parser("historical-batch")
    batch.add_argument("--underlying", required=True)
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--wings", required=True, type=int)
    batch.add_argument("--output")
    evidence = subparsers.add_parser("historical-evidence")
    evidence.add_argument("--underlying", required=True)
    evidence.add_argument("--manifest", required=True)
    evidence.add_argument("--wings", required=True, type=int)
    evidence.add_argument("--output")
    evidence.add_argument("--csv-output")
    evidence.add_argument("--cache-dir", default="data/historical-cache")
    evidence.add_argument("--refresh", action="store_true")
    arguments = parser.parse_args()

    if arguments.service == "historical-validate":
        _historical_validate(arguments)
        return
    if arguments.service == "historical-batch":
        _historical_batch(arguments)
        return
    if arguments.service == "historical-evidence":
        _historical_evidence(arguments)
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

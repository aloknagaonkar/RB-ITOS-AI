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


from .historical_oos import (
    freeze_h3_spec_csv,
    load_h3_spec_json,
    validate_h3_oos_csv,
    write_h3_oos_json,
    write_h3_spec_json,
)
from .historical_oos_combined import (
    validate_h3_combined_oos_csv,
    write_h3_combined_oos_json,
)

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



def _historical_analyze(arguments) -> None:
    from .historical_analysis import analyze_historical_evidence_csv, write_historical_analysis_json

    try:
        report = analyze_historical_evidence_csv(arguments.input)
        if arguments.output:
            write_historical_analysis_json(report, arguments.output)
        summary = {
            "status": report.status,
            "source": report.source,
            "row_count": report.row_count,
            "session_count": report.session_count,
            "feature_count": len(report.feature_analyses),
            "output": arguments.output,
        }
        print(json.dumps(summary, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "source": arguments.input,
            "issues": [str(error)],
        }, indent=2))



def _historical_rank(arguments) -> None:
    from .historical_ranking import rank_historical_evidence_csv, write_historical_ranking_json

    try:
        report = rank_historical_evidence_csv(arguments.input)
        if arguments.output:
            write_historical_ranking_json(report, arguments.output)
        ranked_count = sum(item.rank is not None for item in report.ranked_conditions)
        summary = {
            "status": report.status,
            "source": report.source,
            "row_count": report.row_count,
            "session_count": report.session_count,
            "candidate_count": len(report.ranked_conditions),
            "ranked_candidate_count": ranked_count,
            "primary_forward": report.primary_forward,
            "output": arguments.output,
        }
        print(json.dumps(summary, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "source": arguments.input,
            "issues": [str(error)],
        }, indent=2))


def _historical_backtest_hypotheses(arguments) -> None:
    from .historical_hypothesis_backtest import backtest_hypotheses_csv, write_hypothesis_backtest_json

    try:
        report = backtest_hypotheses_csv(arguments.input, arguments.cooldown_minutes)
        if arguments.output:
            write_hypothesis_backtest_json(report, arguments.output)
        summary = {
            "status": report.status,
            "source": report.source,
            "row_count": report.row_count,
            "session_count": report.session_count,
            "cooldown_minutes": report.cooldown_minutes,
            "hypothesis_count": len(report.hypotheses),
            "events": {item.hypothesis_id: item.event_count for item in report.hypotheses},
            "output": arguments.output,
        }
        print(json.dumps(summary, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "source": arguments.input,
            "issues": [str(error)],
        }, indent=2))

def _historical_freeze_h3(arguments) -> None:
    spec = freeze_h3_spec_csv(arguments.input, arguments.cooldown_minutes)
    if arguments.output:
        write_h3_spec_json(spec, arguments.output)
    print(json.dumps({
        "status": "AVAILABLE",
        "source": arguments.input,
        "spec_version": spec.spec_version,
        "hypothesis_id": spec.hypothesis_id,
        "frozen_threshold": spec.frozen_threshold,
        "training_row_count": spec.training_row_count,
        "training_session_count": spec.training_session_count,
        "cooldown_minutes": spec.cooldown_minutes,
        "output": arguments.output,
    }, indent=2))


def _historical_validate_h3_oos(arguments) -> None:
    spec = load_h3_spec_json(arguments.spec)
    report = validate_h3_oos_csv(arguments.input, spec)
    if arguments.output:
        write_h3_oos_json(report, arguments.output)
    primary = report.holds.get("15m")
    print(json.dumps({
        "status": report.status,
        "source": arguments.input,
        "spec": arguments.spec,
        "frozen_threshold": report.frozen_threshold,
        "row_count": report.row_count,
        "session_count": report.session_count,
        "event_count": report.event_count,
        "event_session_count": report.event_session_count,
        "win_rate_15m": primary.win_rate_pct if primary else None,
        "mean_15m": primary.mean_directional_points if primary else None,
        "median_15m": primary.median_directional_points if primary else None,
        "acceptance_status": report.acceptance_status,
        "output": arguments.output,
    }, indent=2))

def _historical_validate_h3_combined_oos(arguments) -> None:
    spec = load_h3_spec_json(arguments.spec)
    report = validate_h3_combined_oos_csv(arguments.block_a, arguments.block_b, spec)
    if arguments.output:
        write_h3_combined_oos_json(report, arguments.output)
    primary = report.combined.holds.get("15m")
    print(json.dumps({
        "status": report.status,
        "spec": arguments.spec,
        "frozen_threshold": report.frozen_threshold,
        "block_a_sessions": report.block_a.session_count,
        "block_b_sessions": report.block_b.session_count,
        "combined_sessions": report.combined.session_count,
        "combined_event_count": report.combined.event_count,
        "combined_event_session_count": report.combined.event_session_count,
        "combined_win_rate_15m": primary.win_rate_pct if primary else None,
        "combined_mean_15m": primary.mean_directional_points if primary else None,
        "combined_median_15m": primary.median_directional_points if primary else None,
        "robustness_status": report.robustness_status,
        "output": arguments.output,
    }, indent=2))



def _historical_pcr_deep_analyze(arguments) -> None:
    from .pcr_deep_analysis import analyze_pcr_deep_csv, write_pcr_deep_analysis_json

    try:
        report = analyze_pcr_deep_csv(arguments.input)
        if arguments.output:
            write_pcr_deep_analysis_json(report, arguments.output)
        print(json.dumps({
            "status": report.status,
            "source": report.source,
            "row_count": report.row_count,
            "session_count": report.session_count,
            "panel_count": len(report.panels),
            "cross_panel_condition_count": len(report.cross_panel.conditions),
            "output": arguments.output,
        }, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "source": arguments.input,
            "issues": [str(error)],
        }, indent=2))



def _historical_pcr_deep_compare(arguments) -> None:
    from .pcr_deep_compare import compare_pcr_deep_json, write_pcr_deep_comparison_json

    try:
        report = compare_pcr_deep_json(arguments.training, arguments.oos_a, arguments.oos_b)
        if arguments.output:
            write_pcr_deep_comparison_json(report, arguments.output)
        print(json.dumps({
            "status": report.status,
            "total_row_count": report.total_row_count,
            "total_session_count": report.total_session_count,
            "candidates": [
                {
                    "condition": item.condition,
                    "expected_direction": item.expected_direction,
                    "validation_status": item.validation_status,
                    "consistent_direction_count": item.consistent_direction_count,
                }
                for item in report.candidates
            ],
            "output": arguments.output,
        }, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "issues": [str(error)],
        }, indent=2))



def _historical_pcr_reversal_analyze(arguments) -> None:
    from .pcr_reversal_analysis import analyze_pcr_reversal_csv, write_pcr_reversal_json

    try:
        report = analyze_pcr_reversal_csv(arguments.input)
        if arguments.output:
            write_pcr_reversal_json(report, arguments.output)
        stage2 = next((item for item in report.stages if item.stage.startswith("STAGE_2")), None)
        print(json.dumps({
            "status": report.status,
            "source": report.source,
            "row_count": report.row_count,
            "session_count": report.session_count,
            "stage_2_event_count": stage2.event_count if stage2 else 0,
            "stage_2_event_session_count": stage2.session_count if stage2 else 0,
            "stage_2_pcr_led_price_pct": stage2.pcr_led_price_pct if stage2 else None,
            "stage_2_mean_lead_minutes": stage2.mean_lead_minutes if stage2 else None,
            "stage_2_bearish_pct_15m": stage2.bearish_pct_15m if stage2 else None,
            "output": arguments.output,
        }, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "source": arguments.input,
            "issues": [str(error)],
        }, indent=2))


def _historical_pcr_reversal_compare(arguments) -> None:
    from .pcr_reversal_compare import compare_reversal_report_files, write_pcr_reversal_100_json

    try:
        report = compare_reversal_report_files(
            arguments.training, arguments.oos_a, arguments.oos_b, arguments.oos_c, arguments.oos_d
        )
        if arguments.output:
            write_pcr_reversal_100_json(report, arguments.output)
        print(json.dumps({
            "status": report.status,
            "stage": report.stage,
            "block_count": report.block_count,
            "total_row_count": report.total_row_count,
            "total_session_count": report.total_session_count,
            "bearish_direction_block_count": report.bearish_direction_block_count,
            "lead_support_block_count": report.lead_support_block_count,
            "combined_event_count": report.combined.event_count,
            "combined_pcr_led_price_pct": report.combined.pcr_led_price_pct,
            "combined_mean_lead_minutes": report.combined.mean_lead_minutes,
            "combined_bearish_pct_15m": report.combined.bearish_pct_15m,
            "robustness_status": report.robustness_status,
            "output": arguments.output,
        }, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "issues": [str(error)],
        }, indent=2))



def _historical_pcr_stage2_discriminate(arguments) -> None:
    from .pcr_stage2_discriminator import analyze_stage2_discriminator, write_stage2_discriminator_json

    try:
        blocks = [(name, evidence, reversal) for name, evidence, reversal in arguments.block]
        report = analyze_stage2_discriminator(blocks)
        if arguments.output:
            write_stage2_discriminator_json(report, arguments.output)
        print(json.dumps({
            "status": report.status,
            "stage": report.stage,
            "block_count": report.block_count,
            "total_evidence_rows": report.total_evidence_rows,
            "total_stage_2_events": report.total_stage_2_events,
            "total_joined_events": report.total_joined_events,
            "total_success_events": report.total_success_events,
            "total_false_warning_events": report.total_false_warning_events,
            "top_features": [
                {
                    "feature": item.feature,
                    "standardized_median_difference": item.standardized_median_difference,
                    "block_direction_consistency_count": item.block_direction_consistency_count,
                    "block_available_count": item.block_available_count,
                }
                for item in report.features[:8]
            ],
            "output": arguments.output,
        }, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "issues": [str(error)],
        }, indent=2))



def _historical_pcr_bidirectional_compare(arguments) -> None:
    from .pcr_bidirectional_reversal import analyze_bidirectional_blocks, write_bidirectional_json

    try:
        blocks = [(name, evidence) for name, evidence in arguments.block]
        report = analyze_bidirectional_blocks(blocks)
        if arguments.output:
            write_bidirectional_json(report, arguments.output)
        print(json.dumps({
            "status": report.status,
            "block_count": report.block_count,
            "total_row_count": report.total_row_count,
            "total_session_count": report.total_session_count,
            "bearish": {
                "event_count": report.bearish.combined.event_count,
                "pcr_led_price_pct": report.bearish.combined.pcr_led_price_pct,
                "mean_lead_minutes": report.bearish.combined.mean_lead_minutes,
                "directional_pct_15m": report.bearish.combined.directional_pct_15m,
                "direction_support_block_count": report.bearish.combined.direction_support_block_count,
                "lead_support_block_count": report.bearish.combined.lead_support_block_count,
                "robustness_status": report.bearish.combined.robustness_status,
            },
            "bullish": {
                "event_count": report.bullish.combined.event_count,
                "pcr_led_price_pct": report.bullish.combined.pcr_led_price_pct,
                "mean_lead_minutes": report.bullish.combined.mean_lead_minutes,
                "directional_pct_15m": report.bullish.combined.directional_pct_15m,
                "direction_support_block_count": report.bullish.combined.direction_support_block_count,
                "lead_support_block_count": report.bullish.combined.lead_support_block_count,
                "robustness_status": report.bullish.combined.robustness_status,
            },
            "output": arguments.output,
        }, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "UNAVAILABLE", "issues": [str(error)]}, indent=2))


def _historical_pcr_bidirectional_discriminate(arguments) -> None:
    from .pcr_bidirectional_discriminator import analyze_bidirectional_discriminator, write_bidirectional_discriminator_json

    try:
        blocks = [(name, evidence) for name, evidence in arguments.block]
        report = analyze_bidirectional_discriminator(blocks)
        if arguments.output:
            write_bidirectional_discriminator_json(report, arguments.output)
        print(json.dumps({
            "status": report.status,
            "block_count": report.block_count,
            "total_evidence_rows": report.total_evidence_rows,
            "total_session_count": report.total_session_count,
            "bearish": {
                "stage_2_events": report.bearish.total_stage_2_events,
                "true_reversals": report.bearish.total_true_reversals,
                "false_warnings": report.bearish.total_false_warnings,
                "top_features": [
                    {
                        "feature": item.feature,
                        "standardized_median_difference": item.standardized_median_difference,
                        "block_direction_consistency_count": item.block_direction_consistency_count,
                        "block_available_count": item.block_available_count,
                    } for item in report.bearish.features[:6]
                ],
            },
            "bullish": {
                "stage_2_events": report.bullish.total_stage_2_events,
                "true_reversals": report.bullish.total_true_reversals,
                "false_warnings": report.bullish.total_false_warnings,
                "top_features": [
                    {
                        "feature": item.feature,
                        "standardized_median_difference": item.standardized_median_difference,
                        "block_direction_consistency_count": item.block_direction_consistency_count,
                        "block_available_count": item.block_available_count,
                    } for item in report.bullish.features[:6]
                ],
            },
            "output": arguments.output,
        }, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "UNAVAILABLE", "issues": [str(error)]}, indent=2))

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
    analyze = subparsers.add_parser("historical-analyze")
    analyze.add_argument("--input", required=True)
    analyze.add_argument("--output")
    rank = subparsers.add_parser("historical-rank")
    rank.add_argument("--input", required=True)
    rank.add_argument("--output")
    backtest = subparsers.add_parser("historical-backtest-hypotheses")
    backtest.add_argument("--input", required=True)
    backtest.add_argument("--output")
    backtest.add_argument("--cooldown-minutes", type=int, default=15)
    freeze_h3 = subparsers.add_parser("historical-freeze-h3")
    freeze_h3.add_argument("--input", required=True)
    freeze_h3.add_argument("--output", required=True)
    freeze_h3.add_argument("--cooldown-minutes", type=int, default=15)
    oos_h3 = subparsers.add_parser("historical-validate-h3-oos")
    oos_h3.add_argument("--input", required=True)
    oos_h3.add_argument("--spec", required=True)
    oos_h3.add_argument("--output", required=True)
    combined_oos_h3 = subparsers.add_parser("historical-validate-h3-combined-oos")
    combined_oos_h3.add_argument("--block-a", required=True)
    combined_oos_h3.add_argument("--block-b", required=True)
    combined_oos_h3.add_argument("--spec", required=True)
    combined_oos_h3.add_argument("--output", required=True)
    pcr_deep = subparsers.add_parser("historical-pcr-deep-analyze")
    pcr_deep.add_argument("--input", required=True)
    pcr_deep.add_argument("--output")
    pcr_compare = subparsers.add_parser("historical-pcr-deep-compare")
    pcr_compare.add_argument("--training", required=True)
    pcr_compare.add_argument("--oos-a", required=True)
    pcr_compare.add_argument("--oos-b", required=True)
    pcr_compare.add_argument("--output")
    pcr_reversal = subparsers.add_parser("historical-pcr-reversal-analyze")
    pcr_reversal.add_argument("--input", required=True)
    pcr_reversal.add_argument("--output")
    pcr_reversal_compare = subparsers.add_parser("historical-pcr-reversal-compare")
    pcr_reversal_compare.add_argument("--training", required=True)
    pcr_reversal_compare.add_argument("--oos-a", required=True)
    pcr_reversal_compare.add_argument("--oos-b", required=True)
    pcr_reversal_compare.add_argument("--oos-c", required=True)
    pcr_reversal_compare.add_argument("--oos-d", required=True)
    pcr_reversal_compare.add_argument("--output")
    stage2_discriminator = subparsers.add_parser("historical-pcr-stage2-discriminate")
    stage2_discriminator.add_argument(
        "--block", action="append", nargs=3, required=True,
        metavar=("NAME", "EVIDENCE_CSV", "REVERSAL_JSON"),
        help="Repeat for each frozen block: NAME evidence.csv reversal.json",
    )
    stage2_discriminator.add_argument("--output")
    bidirectional = subparsers.add_parser("historical-pcr-bidirectional-compare")
    bidirectional.add_argument(
        "--block", action="append", nargs=2, required=True,
        metavar=("NAME", "EVIDENCE_CSV"),
        help="Repeat for each frozen block: NAME evidence.csv",
    )
    bidirectional.add_argument("--output")
    bidirectional_discriminator = subparsers.add_parser("historical-pcr-bidirectional-discriminate")
    bidirectional_discriminator.add_argument(
        "--block", action="append", nargs=2, required=True,
        metavar=("NAME", "EVIDENCE_CSV"),
        help="Repeat for each frozen block. First block must be TRAIN: NAME evidence.csv",
    )
    bidirectional_discriminator.add_argument("--output")
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
    if arguments.service == "historical-analyze":
        _historical_analyze(arguments)
        return
    if arguments.service == "historical-rank":
        _historical_rank(arguments)
        return
    if arguments.service == "historical-backtest-hypotheses":
        _historical_backtest_hypotheses(arguments)
        return
    if arguments.service == "historical-freeze-h3":
        _historical_freeze_h3(arguments)
        return
    if arguments.service == "historical-validate-h3-oos":
        _historical_validate_h3_oos(arguments)
        return
    if arguments.service == "historical-validate-h3-combined-oos":
        _historical_validate_h3_combined_oos(arguments)
        return
    if arguments.service == "historical-pcr-deep-analyze":
        _historical_pcr_deep_analyze(arguments)
        return
    if arguments.service == "historical-pcr-deep-compare":
        _historical_pcr_deep_compare(arguments)
        return
    if arguments.service == "historical-pcr-reversal-analyze":
        _historical_pcr_reversal_analyze(arguments)
        return
    if arguments.service == "historical-pcr-reversal-compare":
        _historical_pcr_reversal_compare(arguments)
        return
    if arguments.service == "historical-pcr-stage2-discriminate":
        _historical_pcr_stage2_discriminate(arguments)
        return
    if arguments.service == "historical-pcr-bidirectional-compare":
        _historical_pcr_bidirectional_compare(arguments)
        return
    if arguments.service == "historical-pcr-bidirectional-discriminate":
        _historical_pcr_bidirectional_discriminate(arguments)
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

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MODEL = "HISTORICAL_REPLAY_PARITY_V1_2"

SUMMARY_KEYS = (
    "checkpoint_count",
    "processed_checkpoint_count",
    "missing_checkpoint_count",
    "observation_count",
    "state_counts",
    "step_audit_rows",
    "step_audit_chain_ok",
)

IGNORE_AUDIT_HASH_KEYS = {"record_hash", "previous_hash"}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _strip_hashes(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in IGNORE_AUDIT_HASH_KEYS}


def compare(
    baseline_dir: str | Path,
    candidate_dir: str | Path,
) -> dict[str, Any]:
    baseline_dir = Path(baseline_dir)
    candidate_dir = Path(candidate_dir)

    b_status = _load_json(baseline_dir / "replay-status.json")
    c_status = _load_json(candidate_dir / "replay-status.json")

    summary = {
        key: {
            "baseline": b_status.get(key),
            "candidate": c_status.get(key),
            "equal": b_status.get(key) == c_status.get(key),
        }
        for key in SUMMARY_KEYS
    }

    trade_equal = b_status.get("trades") == c_status.get("trades")

    b_events = _load_jsonl(baseline_dir / "events.jsonl")
    c_events = _load_jsonl(candidate_dir / "events.jsonl")
    events_semantic_equal = (
        [_strip_hashes(x) for x in b_events]
        == [_strip_hashes(x) for x in c_events]
    )

    b_health = _load_jsonl(baseline_dir / "health.jsonl")
    c_health = _load_jsonl(candidate_dir / "health.jsonl")
    health_equal = b_health == c_health

    b_audit = _load_jsonl(baseline_dir / "step-audit.jsonl")
    c_audit = _load_jsonl(candidate_dir / "step-audit.jsonl")
    audit_semantic_equal = (
        [_strip_hashes(x) for x in b_audit]
        == [_strip_hashes(x) for x in c_audit]
    )

    passed = (
        all(v["equal"] for v in summary.values())
        and trade_equal
        and events_semantic_equal
        and health_equal
        and audit_semantic_equal
        and c_status.get("step_audit_chain_ok") is True
    )

    return {
        "model": MODEL,
        "passed": passed,
        "summary": summary,
        "trades_equal": trade_equal,
        "events_semantic_equal": events_semantic_equal,
        "health_equal": health_equal,
        "step_audit_semantic_equal": audit_semantic_equal,
        "candidate_chain_ok": c_status.get("step_audit_chain_ok"),
        "baseline_event_rows": len(b_events),
        "candidate_event_rows": len(c_events),
        "baseline_health_rows": len(b_health),
        "candidate_health_rows": len(c_health),
        "baseline_audit_rows": len(b_audit),
        "candidate_audit_rows": len(c_audit),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    result = compare(args.baseline, args.candidate)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()

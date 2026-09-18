from pathlib import Path

PATH = Path("backend/market_lab/historical_replay_operations_api_v1.py")
text = PATH.read_text(encoding="utf-8")

needle = "from .historical_replay_data_v1 import readiness\n"
replacement = needle + "from .historical_replay_strict_readiness_v1 import snapshot_checkpoint_coverage\n"
if "historical_replay_strict_readiness_v1" not in text:
    if needle not in text:
        raise SystemExit("Safe-stop: readiness import not found.")
    text = text.replace(needle, replacement, 1)

text = text.replace(
    'elif name in {"futures","futures_1m","futures-1m"}:',
    'elif name in {"futures","futures_1m","futures-1m","nifty_futures_1m"}:',
)

old = (
"def _readiness_response(session_date: date) -> dict[str, Any]:\n"
"    current = readiness(session_date)\n"
"    return {\"model\": MODEL, \"session_date\": session_date.isoformat(),\n"
"            \"readiness\": current, \"datasets\": _dataset_semantics(current),\n"
"            \"active_job\": _active_for_date(session_date)}\n"
)

new = (
"def _readiness_response(session_date: date) -> dict[str, Any]:\n"
"    current = readiness(session_date)\n"
"    coverage = snapshot_checkpoint_coverage(session_date)\n"
"    datasets = _dataset_semantics(current)\n"
"\n"
"    for row in datasets:\n"
"        name = str(row.get(\"name\") or \"\").lower()\n"
"        if name in {\"option_chain_snapshots\",\"option-chain-snapshots\",\"snapshots\"}:\n"
"            row[\"checkpoint_coverage\"] = coverage\n"
"            if not coverage.get(\"coverage_complete\"):\n"
"                row[\"operation_status\"] = \"PARTIAL\"\n"
"                row[\"operation_detail\"] = (\n"
"                    f\"{coverage.get('covered_checkpoint_count',0)}/\"\n"
"                    f\"{coverage.get('expected_checkpoint_count',0)} exact 5-minute checkpoints covered. \"\n"
"                    \"Missing historical snapshots are not downloadable by this pipeline.\"\n"
"                )\n"
"\n"
"    futures_ready = any(\n"
"        str(row.get(\"name\") or \"\").lower() in {\"nifty_futures_1m\",\"futures\",\"futures_1m\",\"futures-1m\"}\n"
"        and str(row.get(\"status\") or \"\").upper() in {\"AVAILABLE\",\"READY\"}\n"
"        for row in datasets\n"
"    )\n"
"    strict_ready = bool(coverage.get(\"coverage_complete\") and futures_ready)\n"
"\n"
"    return {\n"
"        \"model\": MODEL,\n"
"        \"session_date\": session_date.isoformat(),\n"
"        \"readiness\": current,\n"
"        \"datasets\": datasets,\n"
"        \"snapshot_checkpoint_coverage\": coverage,\n"
"        \"strict_replay_ready\": strict_ready,\n"
"        \"active_job\": _active_for_date(session_date),\n"
"    }\n"
)

if old not in text:
    raise SystemExit("Safe-stop: _readiness_response block not found.")
text = text.replace(old, new, 1)

old_run = (
"@router.post(\"/run\")\n"
"def replay_ops_run(request: ReplayRunRequest):\n"
"    current = readiness(request.session_date)\n"
"    ready = bool(current.get(\"checkpoint_replay_ready\") or current.get(\"checkpoint_ready\")\n"
"                 or current.get(\"full_replay_prerequisites_ready\")\n"
"                 or current.get(\"full_trade_replay_prerequisites_ready\"))\n"
"    if not ready:\n"
"        raise HTTPException(409, {\"message\":\"Replay prerequisites are not ready. Check readiness/download missing first.\",\n"
"                                  \"readiness\":current,\"datasets\":_dataset_semantics(current)})\n"
"    return _launch(\"RUN_REPLAY\", request.session_date, overwrite=request.overwrite)\n"
)

new_run = (
"@router.post(\"/run\")\n"
"def replay_ops_run(request: ReplayRunRequest):\n"
"    status = _readiness_response(request.session_date)\n"
"    if not status.get(\"strict_replay_ready\"):\n"
"        raise HTTPException(409, {\n"
"            \"message\": \"Replay prerequisites are not strictly ready. Exact 5-minute snapshot coverage and futures data are required.\",\n"
"            \"readiness\": status.get(\"readiness\"),\n"
"            \"datasets\": status.get(\"datasets\"),\n"
"            \"snapshot_checkpoint_coverage\": status.get(\"snapshot_checkpoint_coverage\"),\n"
"        })\n"
"    return _launch(\"RUN_REPLAY\", request.session_date, overwrite=request.overwrite)\n"
)

if old_run not in text:
    raise SystemExit("Safe-stop: replay_ops_run block not found.")
text = text.replace(old_run, new_run, 1)

PATH.write_text(text, encoding="utf-8")
print("Historical Replay strict readiness V1.2 applied.")

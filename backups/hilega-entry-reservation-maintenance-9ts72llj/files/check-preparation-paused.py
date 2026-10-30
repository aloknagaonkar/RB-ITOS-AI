import json
from datetime import datetime, time
from pathlib import Path
import sqlite3
import sys

from market_lab.domain import IST
from market_lab.hilega_production_bridge_health_v1 import effective
from market_lab.hilega_production_simulator_bridge_v1 import verified_records

repo = Path.cwd().resolve()
sys.path.insert(0, str(repo / "hilega-production-application-deployment"))
from managed_processes import inspect as inventory

maintenance = json.loads((
    repo / "backups/hilega-preparation-activation-cvtlkibq/maintenance.json"
).read_text())
processes = inventory(repo)
actual = processes["active_processes"]
expected = maintenance["children"]

process_match = (
    len(actual) == 3
    and {(r["role"], r["pid"]) for r in actual} == {
        ("api", expected["api"]),
        ("worker", expected["worker"]),
        ("production-source-worker", expected["source"]),
    }
)

database = repo / "data/research/hilega-production-workspace/sim.sqlite"
if not database.is_file() or database.is_symlink():
    raise SystemExit("STOP: regular existing database required")
db = sqlite3.connect(database.as_uri()+"?mode=ro", uri=True)
try:
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    control = json.loads(db.execute(
        "SELECT data FROM control WHERE id=1"
    ).fetchone()[0])
    route = json.loads(db.execute(
        "SELECT data FROM preparation_route WHERE id=1"
    ).fetchone()[0])
    health_row = json.loads(db.execute(
        "SELECT data FROM sim_bridge_health WHERE id=1"
    ).fetchone()[0])
    cursor = json.loads(db.execute(
        "SELECT data FROM preparation_source WHERE id=1"
    ).fetchone()[0])
    names = (
        "intents", "sim_orders", "sim_fills", "sim_allocation_reservations",
        "preparation_plans", "preparation_shadow_holds", "preparation_outbox",
    )
    counts = {
        n: db.execute("SELECT COUNT(*) FROM "+n).fetchone()[0]
        for n in names
    }
    recent = [
        json.loads(r[0]) for r in db.execute(
            "SELECT data FROM preparation_events ORDER BY seq DESC LIMIT 3"
        )
    ]
finally:
    db.close()

journal = repo / "data/live-observation/hilega-directional-v1/step-audit.jsonl"
records = list(verified_records(journal))
sequence = cursor["sequence"]
prefix_matches = (
    cursor["path"] == str(journal.resolve())
    and type(sequence) is int
    and 0 <= sequence <= len(records)
    and cursor["hash"] == (
        records[sequence-1]["record_hash"] if sequence else None
    )
)

now = datetime.now(IST)
health = effective(health_row, now)
heartbeat_age = health.get("heartbeat_age_seconds")
worker_operational = (
    health_row.get("pid") == expected["source"]
    and health_row.get("phase") == "RUNNING"
    and health_row.get("session_date") == now.date().isoformat()
    and heartbeat_age is not None
    and 0 <= heartbeat_age <= health["heartbeat_limit_seconds"]
)
safe = (
    process_match
    and control["mode"] == "PAUSED"
    and route == {
        "route": "PREPARATION_ONLY",
        "model": "APPLICATION_PREPARATION_ROUTE_V1",
    }
    and not any(counts.values())
    and prefix_matches
)

status = (
    "PAUSED_SAFETY_CHECK_FAILED" if not safe
    else "WORKER_HEALTH_REQUIRES_REVIEW" if not worker_operational
    else "PAUSED_SAFE_SOURCE_FRESH" if health["healthy"]
    else "PAUSED_SAFE_WAITING_FOR_FRESH_SOURCE"
)
print(json.dumps({
    "status": status,
    "checked_at_IST": now.isoformat(),
    "process_identities_match": process_match,
    "execution_route": route["route"],
    "controller_mode": control["mode"],
    "activity_counts": counts,
    "journal_prefix_matches": prefix_matches,
    "journal_tail_remaining_records": len(records)-sequence,
    "bridge_health": health,
    "within_configured_entry_clock_window": (
        time(9,15) <= now.time() < time(14,55)
    ),
    "recent_preparation_outcomes": [
        {k: r.get(k) for k in ("status", "reasons", "at")}
        for r in recent
    ],
    "fresh_signal_admission_verified": False,
    "broker_reads_performed_by_this_check": False,
    "production_ready": False,
}, indent=2))
raise SystemExit(0 if safe and worker_operational else 1)
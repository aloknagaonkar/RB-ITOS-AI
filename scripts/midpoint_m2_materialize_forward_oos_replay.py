#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")

UNDERLYING = Path(
    "data/historical-evidence/midpoint-forward-sep2026-underlying.csv"
)
FUTURES = Path(
    "data/historical-evidence/midpoint-forward-sep2026-futures-vwap.csv"
)
OUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)

SOURCE = "FORWARD_OOS_REPLAY"
BLOCK = "FORWARD_OOS_2026-09"

TRUSTED_START = "09:15"
TRUSTED_END = "15:14"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
PY  main()_ == "__main__":RCE,nute_rows),) + "\n",R"_rows]{bad[:10]}"d 360"cted 360"
(.venv) aloknagaonkar46@high-perf-db-vm:~/RB-ITOS-AI$ python - <<'PY'
import json
from pathlib import Path

root = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)

m = json.loads((root / "manifest.json").read_text())

print("total sessions:", m["session_count"])
print()

for s in m["sessions"][:20]:
    print(
        s["session_date"],
        "events=", s.get("event_count"),
        "minutes=", s.get("minute_count"),
        "source=", s.get("source"),
    )

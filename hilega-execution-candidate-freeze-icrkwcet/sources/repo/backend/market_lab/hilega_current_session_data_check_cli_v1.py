from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
DEFAULT_URL = "http://127.0.0.1:8123/api/live-shadow/hilega-directional/status?fast=true"


def evaluate_status(payload: dict, today: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("API response is not a JSON object.")
    current = payload.get("current")
    if not isinstance(current, dict) or "state_available" not in current:
        raise ValueError(
            "API response is missing current.state_available; install the current-session status patch first."
        )

    session_date = str(current.get("session_date") or "")
    last_bar = current.get("last_completed_bar")
    last_bar = str(last_bar) if last_bar else None
    last_bar_date = last_bar[:10] if last_bar else None
    state_record_today = (
        session_date == today and current.get("state_available") is True
    )
    bar_today = last_bar_date == today
    return {
        "session_date": session_date,
        "state_record_today": state_record_today,
        "last_completed_bar": last_bar,
        "bar_today": bar_today,
        "latest_state_session_date": payload.get("latest_state_session_date"),
        "ok": state_record_today and bar_today,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m market_lab.hilega_current_session_data_check_cli_v1"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Status API URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout in seconds")
    args = parser.parse_args()

    today = datetime.now(IST).date().isoformat()
    try:
        with urlopen(args.url, timeout=args.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = evaluate_status(payload, today)
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"API CHECK FAILED: {exc}", file=sys.stderr)
        return 2

    print(f"Expected IST session date: {today}")
    print(f"API session date: {result['session_date'] or 'missing'}")
    print(f"Today's state record: {'YES' if result['state_record_today'] else 'NO'}")
    print(f"Latest completed bar: {result['last_completed_bar'] or 'missing'}")
    print(f"Latest saved state date: {result['latest_state_session_date'] or 'none'}")

    if result["ok"]:
        print("PASS: today's state record and completed bar are being returned.")
        return 0
    if result["state_record_today"]:
        print("INCOMPLETE: today's state exists, but no completed bar dated today was returned.")
    else:
        print("NO CURRENT DATA: the API has not returned a state record for today.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

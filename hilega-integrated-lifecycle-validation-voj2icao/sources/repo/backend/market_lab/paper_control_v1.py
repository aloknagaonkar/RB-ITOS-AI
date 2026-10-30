
from __future__ import annotations

import argparse
import json

from sqlalchemy.orm import Session

from .paper_production_storage_v1 import (
    ensure_paper_schema,
    paper_detail_view,
    paper_quick_view,
    set_paper_enabled,
)
from .storage import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m market_lab.paper_control_v1")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("status")

    enable = sub.add_parser("enable")
    enable.add_argument(
        "--confirm",
        required=True,
        choices=["PAPER_ONLY"],
        help="Explicit manual approval token. Live execution remains impossible.",
    )
    sub.add_parser("disable")

    detail = sub.add_parser("detail")
    detail.add_argument("--limit", type=int, default=250)

    args = parser.parse_args()
    engine = make_engine()
    ensure_paper_schema(engine)

    if args.command == "init":
        print(json.dumps({"status": "READY", "paper_enabled": False, "live_enabled": False}, indent=2))
        return

    if args.command == "enable":
        print(json.dumps(set_paper_enabled(engine, True), indent=2))
        return

    if args.command == "disable":
        print(json.dumps(set_paper_enabled(engine, False), indent=2))
        return

    with Session(engine) as session:
        if args.command == "status":
            print(json.dumps(paper_quick_view(session), indent=2))
        elif args.command == "detail":
            print(json.dumps(paper_detail_view(session, args.limit), indent=2))


if __name__ == "__main__":
    main()

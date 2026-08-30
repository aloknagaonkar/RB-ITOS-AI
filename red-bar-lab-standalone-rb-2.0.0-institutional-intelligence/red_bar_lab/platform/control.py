"""CLI entry point for the cross-platform platform controller.

Usage:
    python -m red_bar_lab.platform.control start
    python -m red_bar_lab.platform.control stop
    python -m red_bar_lab.platform.control status
    python -m red_bar_lab.platform.control restart
    python -m red_bar_lab.platform.control serve
"""

from __future__ import annotations

import argparse
import logging
import sys

from red_bar_lab.platform.config import PlatformConfig
from red_bar_lab.platform.supervisor import PlatformSupervisor


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="red-bar-platform",
        description="Cross-platform process supervisor for the Red Bar trading platform.",
    )
    parser.add_argument(
        "action",
        choices=["start", "stop", "status", "restart", "serve"],
        help="Platform action: start, stop, status, restart, or serve (foreground).",
    )
    parser.add_argument("--underlying", default=None, help="Override underlying (NIFTY 50 or BANK NIFTY)")
    parser.add_argument("--ui-port", type=int, default=None, help="Override UI port")
    parser.add_argument("--collector-interval", type=int, default=None, help="Override collector interval seconds")
    parser.add_argument("--no-market-research", action="store_true", help="Disable market trend research worker")

    args = parser.parse_args(argv)

    _configure_logging()

    overrides = {}
    if args.underlying:
        overrides["underlying"] = args.underlying
    if args.ui_port:
        overrides["ui_port"] = args.ui_port
    if args.collector_interval:
        overrides["collector_interval_seconds"] = args.collector_interval
    if args.no_market_research:
        overrides["start_market_research"] = False

    config = PlatformConfig(**overrides)

    validation_errors = config.validate()
    if validation_errors and args.action in {"start", "serve", "restart"}:
        sys.stderr.write(
            "Platform configuration is invalid; refusing to start:\n"
        )
        for err in validation_errors:
            sys.stderr.write(f"  - {err}\n")
        sys.stderr.write(
            "\nFix the above (e.g. set UPSTOX_ACCESS_TOKEN in your shell or "
            "in a .env file at the project root) and re-run.\n"
        )
        return 2

    supervisor = PlatformSupervisor(config)

    actions = {
        "start": supervisor.start,
        "stop": supervisor.stop,
        "status": supervisor.status,
        "restart": supervisor.restart,
        "serve": supervisor.serve,
    }

    return actions[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())

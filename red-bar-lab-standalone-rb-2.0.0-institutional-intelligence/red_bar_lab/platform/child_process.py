"""Declarative child-process specifications for the platform supervisor."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class ChildProcessSpec:
    """Declarative specification for a platform child process."""

    name: str
    module: str
    args: List[str] = field(default_factory=list)
    env_extras: dict = field(default_factory=dict)
    startup_timeout_seconds: float = 15.0
    heartbeat_fresh_seconds: float = 30.0
    heartbeat_stale_seconds: float = 90.0
    required: bool = True
    restart: bool = True

    def command(self, project_root: Path) -> List[str]:
        return [sys.executable, "-m", self.module, *self.args]


def build_component_specs(cfg) -> List[ChildProcessSpec]:
    """Build the ordered list of child-process specs from PlatformConfig."""
    project_root = cfg.project_root

    # Forward tokens needed by child processes
    forward_env = {}
    for key in ("UPSTOX_ACCESS_TOKEN",):
        val = os.environ.get(key)
        if val:
            forward_env[key] = val

    specs = [
        ChildProcessSpec(
            name="market_collector",
            module="red_bar_lab.collector.runner",
            args=[
                "--underlying", cfg.underlying,
                "--interval-seconds", str(cfg.collector_interval_seconds),
                "--mode", "auto",
            ],
            heartbeat_fresh_seconds=cfg.collector_interval_seconds + 30,
            heartbeat_stale_seconds=cfg.collector_interval_seconds * 3,
        ),
        ChildProcessSpec(
            name="paper_monitor",
            module="red_bar_lab.execution.paper_monitor",
            args=[
                "--interval-seconds", str(cfg.paper_monitor_interval_seconds),
                "--capital", str(cfg.capital),
                "--underlying", cfg.underlying,
                "--lots", str(cfg.lots),
                "--minimum-score", str(cfg.minimum_score),
            ],
            env_extras=forward_env,
            heartbeat_fresh_seconds=15.0,
            heartbeat_stale_seconds=30.0,
        ),
        ChildProcessSpec(
            name="position_monitor",
            module="red_bar_lab.execution.position_monitor",
            args=[
                "--underlying", cfg.underlying,
                "--interval-seconds", str(cfg.position_monitor_interval_seconds),
            ],
            env_extras=forward_env,
            heartbeat_fresh_seconds=15.0,
            heartbeat_stale_seconds=30.0,
            required=False,
        ),
    ]

    if cfg.start_market_research:
        specs.append(
            ChildProcessSpec(
                name="market_research",
                module="red_bar_lab.execution.run_market_trend_research_supervisor",
                heartbeat_fresh_seconds=20.0,
                heartbeat_stale_seconds=40.0,
                required=False,
            )
        )

    specs.append(
        ChildProcessSpec(
            name="ui",
            module="streamlit",
            args=[
                "run", str(project_root / "red_bar_lab" / "app.py"),
                "--server.port", str(cfg.ui_port),
                "--server.headless", "true",
            ],
            heartbeat_fresh_seconds=999999.0,
            heartbeat_stale_seconds=999999.0,
            required=True,
            restart=True,
        )
    )

    return specs

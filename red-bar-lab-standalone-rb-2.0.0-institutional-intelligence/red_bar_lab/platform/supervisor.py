"""Platform supervisor — orchestrates child process lifecycle."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from red_bar_lab.platform.child_process import ChildProcessSpec, build_component_specs
from red_bar_lab.platform.config import PlatformConfig
from red_bar_lab.platform.process_controller import ProcessController
from red_bar_lab.platform.state_store import AtomicJsonStore, ComponentState, PlatformState

logger = logging.getLogger(__name__)


class PlatformSupervisor:
    """Manages the full lifecycle of platform child processes."""

    def __init__(self, config: PlatformConfig):
        self.config = config
        self._state_dir = config.project_root / config.artifacts_root / "platform"
        self._state_store = AtomicJsonStore(self._state_dir / "platform_state.json")
        self._controller = ProcessController()
        self._specs: List[ChildProcessSpec] = build_component_specs(config)
        self._shutdown_requested = False

    @property
    def state_store(self) -> AtomicJsonStore:
        return self._state_store

    def start(self) -> int:
        """Start all platform components. Returns exit code."""
        errors = self.config.validate()
        if errors:
            for err in errors:
                logger.error("CONFIGURATION_ERROR: %s", err)
            self._write_platform_state("CONFIGURATION_ERROR", reason=errors[0])
            return 2

        existing = self._state_store.read_platform_state()
        if existing.platform_state == "RUNNING":
            logger.error("Platform is already running.")
            self._print_status()
            return 1

        self._write_platform_state("STARTING")
        self._install_signal_handlers()

        started: List[str] = []
        try:
            for spec in self._specs:
                if self._shutdown_requested:
                    break
                try:
                    self._start_component(spec)
                    started.append(spec.name)
                except RuntimeError as exc:
                    if spec.required:
                        raise
                    logger.warning("Non-required %s failed to start: %s", spec.name, exc)
                time.sleep(0.5)

            if not self._shutdown_requested:
                self._write_platform_state("RUNNING")
                logger.info("Platform started successfully.")
                self._print_status()
                return 0
            else:
                self._shutdown()
                return 1
        except Exception as exc:
            logger.error("Startup failed: %s", exc)
            self._shutdown()
            return 1

    def stop(self) -> int:
        """Stop all platform components. Returns exit code."""
        self._write_platform_state("STOPPING")
        self._shutdown()
        return 0

    def status(self) -> int:
        """Print platform status. Returns exit code."""
        self._print_status()
        return 0

    def restart(self) -> int:
        """Restart all platform components. Returns exit code."""
        self.stop()
        time.sleep(2)
        return self.start()

    def serve(self) -> int:
        """Run in foreground mode (for systemd / Docker). Returns exit code."""
        errors = self.config.validate()
        if errors:
            for err in errors:
                logger.error("CONFIGURATION_ERROR: %s", err)
            return 2

        self._write_platform_state("STARTING")
        self._install_signal_handlers()

        started: List[str] = []
        try:
            for spec in self._specs:
                if self._shutdown_requested:
                    break
                try:
                    self._start_component(spec)
                    started.append(spec.name)
                except RuntimeError as exc:
                    if spec.required:
                        raise
                    logger.warning("Non-required %s failed to start: %s", spec.name, exc)
                time.sleep(0.5)

            if self._shutdown_requested:
                self._shutdown()
                return 1

            self._write_platform_state("RUNNING")
            logger.info("Platform running in foreground mode.")

            while not self._shutdown_requested:
                self._check_children()
                time.sleep(5)

            self._shutdown()
            return 0
        except KeyboardInterrupt:
            self._shutdown()
            return 0
        except Exception as exc:
            logger.error("Runtime error: %s", exc)
            self._shutdown()
            return 1

    def _start_component(self, spec: ChildProcessSpec) -> None:
        cmd = spec.command(self.config.project_root)
        env = dict(spec.env_extras)

        logger.info("Starting %s ...", spec.name)
        managed = self._controller.start(spec.name, cmd, env_extras=env if env else None)

        comp_state = ComponentState(
            component=spec.name,
            pid=managed.pid,
            state="STARTING",
            started_at=datetime.now(timezone.utc).isoformat(),
            command=cmd,
        )
        self._state_store.write_component(comp_state)

        deadline = time.monotonic() + spec.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._shutdown_requested:
                return
            if not self._controller.is_running(spec.name):
                exit_code = self._controller.get_exit_code(spec.name)
                comp_state.state = "CRASHED"
                comp_state.last_error = f"Exited with code {exit_code}"
                self._state_store.write_component(comp_state)
                if spec.required:
                    raise RuntimeError(f"{spec.name} exited during startup (code={exit_code})")
                logger.warning("Non-required %s exited (code=%d), skipping.", spec.name, exit_code)
                return
            time.sleep(0.5)

        comp_state.state = "RUNNING"
        self._state_store.write_component(comp_state)
        logger.info("  %s started (pid=%s)", spec.name, managed.pid)

    def _check_children(self) -> None:
        for spec in self._specs:
            if not self._controller.is_running(spec.name):
                continue
            managed = self._controller._managed.get(spec.name)
            if managed and managed.proc and managed.proc.poll() is not None:
                exit_code = managed.proc.returncode
                logger.warning("%s exited unexpectedly (code=%d)", spec.name, exit_code)
                comp = self._state_store.read_component(spec.name)
                if comp:
                    comp.state = "CRASHED"
                    comp.last_error = f"Exited with code {exit_code}"
                    self._state_store.write_component(comp)
                if spec.restart and not self._shutdown_requested:
                    logger.info("Restarting %s ...", spec.name)
                    self._start_component(spec)

    def _shutdown(self) -> None:
        self._write_platform_state("STOPPING")

        stop_order = [
            "market_research",
            "market_collector",
            "position_monitor",
            "paper_monitor",
            "ui",
        ]

        for name in stop_order:
            if self._controller.is_running(name):
                logger.info("Stopping %s ...", name)
                stopped = self._controller.stop(name, timeout=15.0)
                comp = self._state_store.read_component(name)
                if comp:
                    comp.state = "STOPPED" if stopped else "CRASHED"
                    self._state_store.write_component(comp)

        self._controller.stop_all(timeout=5.0)

        self._kill_orphaned_from_state(stop_order)

        self._write_platform_state("STOPPED")
        logger.info("Platform stopped.")

    def _kill_orphaned_from_state(self, stop_order: list[str]) -> None:
        components = self._state_store.read_all_components()
        for name in stop_order:
            comp = components.get(name)
            if comp is None or comp.pid is None:
                continue
            if self._controller.is_running(name):
                continue
            if comp.state in ("STOPPED", "CRASHED"):
                continue
            logger.info("Killing orphaned %s (pid=%s) from state file ...", name, comp.pid)
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(comp.pid)],
                        capture_output=True,
                        timeout=10,
                    )
                else:
                    import signal as sig
                    os.killpg(os.getpgid(comp.pid), sig.SIGKILL)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ProcessLookupError):
                pass
            comp.state = "STOPPED"
            self._state_store.write_component(comp)

    def _write_platform_state(self, state: str, reason: Optional[str] = None) -> None:
        platform = self._state_store.read_platform_state()
        platform.platform_state = state
        if state == "RUNNING" and platform.started_at is None:
            platform.started_at = datetime.now(timezone.utc).isoformat()
        if state == "STOPPED":
            platform.started_at = None
        self._state_store.write_platform_state(platform)

    def _install_signal_handlers(self) -> None:
        def handler(signum, frame):
            if self._shutdown_requested:
                return
            logger.info("Received signal %s, shutting down...", signum)
            self._shutdown_requested = True

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _print_status(self) -> None:
        platform = self._state_store.read_platform_state()
        print(f"\nPlatform State: {platform.platform_state}")
        if platform.started_at:
            print(f"Started At:     {platform.started_at}")

        components = self._state_store.read_all_components()
        if not components:
            print("No component states recorded.")
            return

        print(f"\n{'Component':<25} {'State':<15} {'PID':<10} {'Heartbeat':<25} {'Restarts':<10}")
        print("-" * 95)
        for name, comp in sorted(components.items()):
            heartbeat = comp.heartbeat_at or "—"
            if len(heartbeat) > 24:
                heartbeat = heartbeat[:24]
            pid_str = str(comp.pid) if comp.pid else "—"
            print(f"{comp.component:<25} {comp.state:<15} {pid_str:<10} {heartbeat:<25} {comp.restart_count:<10}")
        print()

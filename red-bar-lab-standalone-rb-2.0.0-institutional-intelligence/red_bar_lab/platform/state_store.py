"""Atomic JSON state store for platform component heartbeats and PIDs."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ComponentState:
    """Runtime state for a single platform component."""

    component: str
    pid: Optional[int] = None
    state: str = "STOPPED"
    heartbeat_at: Optional[str] = None
    last_cycle_started_at: Optional[str] = None
    last_cycle_completed_at: Optional[str] = None
    last_outcome: Optional[str] = None
    last_error: Optional[str] = None
    restart_count: int = 0
    started_at: Optional[str] = None
    command: list = field(default_factory=list)
    log_path: Optional[str] = None
    safe_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> ComponentState:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PlatformState:
    """Aggregate platform state."""

    platform_state: str = "STOPPED"
    started_at: Optional[str] = None
    components: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "platform_state": self.platform_state,
            "started_at": self.started_at,
            "components": {
                name: comp.to_dict() if isinstance(comp, ComponentState) else comp
                for name, comp in self.components.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> PlatformState:
        components = {}
        for name, comp_data in data.get("components", {}).items():
            if isinstance(comp_data, dict):
                components[name] = ComponentState.from_dict(comp_data)
            else:
                components[name] = comp_data
        return cls(
            platform_state=data.get("platform_state", "STOPPED"),
            started_at=data.get("started_at"),
            components=components,
        )


class AtomicJsonStore:
    """Atomic JSON file store for platform state."""

    def __init__(self, path: Path):
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent),
            suffix=".tmp",
            prefix=self._path.stem,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(self._path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def read_platform_state(self) -> PlatformState:
        data = self.read()
        if data is None:
            return PlatformState()
        return PlatformState.from_dict(data)

    def write_platform_state(self, state: PlatformState) -> None:
        self.write(state.to_dict())

    def read_component(self, name: str) -> Optional[ComponentState]:
        state = self.read_platform_state()
        comp = state.components.get(name)
        if isinstance(comp, ComponentState):
            return comp
        return None

    def write_component(self, comp: ComponentState) -> None:
        state = self.read_platform_state()
        state.components[comp.component] = comp
        self.write_platform_state(state)

    def update_heartbeat(self, name: str, **kwargs) -> None:
        comp = self.read_component(name)
        if comp is None:
            comp = ComponentState(component=name)
        now_iso = datetime.now(timezone.utc).isoformat()
        comp.heartbeat_at = now_iso
        for k, v in kwargs.items():
            if hasattr(comp, k):
                setattr(comp, k, v)
        self.write_component(comp)

    def read_all_components(self) -> dict[str, ComponentState]:
        state = self.read_platform_state()
        result = {}
        for name, comp in state.components.items():
            if isinstance(comp, ComponentState):
                result[name] = comp
            elif isinstance(comp, dict):
                result[name] = ComponentState.from_dict(comp)
        return result

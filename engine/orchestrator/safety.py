"""Persisted safety-control state (Requirement 22/23).

Running state, and critically the kill switch, are written to disk on every
change so a crash, restart, or Mac sleep/wake NEVER silently re-enables
trading -- a kill switch that resets itself defeats its entire purpose. On
boot the orchestrator always re-reads this file rather than assuming any
in-memory default.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SafetyState:
    running: bool = False
    kill_switch_active: bool = False
    kill_switch_reason: str = ""


class SafetyController:
    def __init__(self, state_path: Path):
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()

    def _load(self) -> SafetyState:
        if not self.path.exists():
            return SafetyState()
        try:
            return SafetyState(**json.loads(self.path.read_text()))
        except (json.JSONDecodeError, TypeError):
            return SafetyState()

    def _save(self) -> None:
        self.path.write_text(json.dumps(asdict(self.state), indent=2))

    def start(self) -> None:
        if self.state.kill_switch_active:
            raise RuntimeError("Cannot start: kill switch is active. Deactivate it explicitly first.")
        self.state.running = True
        self._save()

    def pause(self) -> None:
        self.state.running = False
        self._save()

    def activate_kill_switch(self, reason: str) -> None:
        self.state.kill_switch_active = True
        self.state.kill_switch_reason = reason
        self.state.running = False
        self._save()

    def deactivate_kill_switch(self) -> None:
        self.state.kill_switch_active = False
        self.state.kill_switch_reason = ""
        self._save()

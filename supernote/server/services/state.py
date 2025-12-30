import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, cast

from mashumaro.mixins.json import DataClassJSONMixin

logger = logging.getLogger(__name__)


@dataclass
class SessionState(DataClassJSONMixin):
    token: str
    username: str
    equipment_no: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)


@dataclass
class UserState(DataClassJSONMixin):
    username: str
    devices: List[str] = field(default_factory=list)


@dataclass
class SystemState(DataClassJSONMixin):
    users: Dict[str, UserState] = field(default_factory=dict)
    sessions: Dict[str, SessionState] = field(default_factory=dict)


class StateService:
    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file
        self._state = self._load()

    def _load(self) -> SystemState:
        if not self.state_file.exists():
            return SystemState()
        try:
            with open(self.state_file, "r") as f:
                return SystemState.from_json(f.read())
        except Exception as e:
            logger.error(f"Failed to load state file {self.state_file}: {e}")
            return SystemState()

    def save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w") as f:
                f.write(cast(str, self._state.to_json()))
        except Exception as e:
            logger.error(f"Failed to save state file {self.state_file}: {e}")

    # User State Methods
    def get_user_state(self, username: str) -> UserState:
        if username not in self._state.users:
            self._state.users[username] = UserState(username=username)
        return self._state.users[username]

    def add_device(self, username: str, equipment_no: str) -> None:
        user_state = self.get_user_state(username)
        if equipment_no not in user_state.devices:
            user_state.devices.append(equipment_no)
            self.save()

    def remove_device(self, equipment_no: str) -> None:
        found = False
        for user_state in self._state.users.values():
            if equipment_no in user_state.devices:
                user_state.devices.remove(equipment_no)
                found = True
        if found:
            self.save()

    # Session Management
    def create_session(
        self, token: str, username: str, equipment_no: str | None = None
    ) -> None:
        session = SessionState(
            token=token, username=username, equipment_no=equipment_no
        )
        self._state.sessions[token] = session
        self.save()

    def get_session(self, token: str) -> SessionState | None:
        session = self._state.sessions.get(token)
        if session:
            session.last_active_at = time.time()
            # We don't necessarily save on every activity to avoid disk thrashing,
            # but maybe we should if persistence is critical.
            # For now, let's just update memory.
        return session

    def prune_sessions(self, max_idle_seconds: int) -> None:
        now = time.time()
        to_remove = [
            token
            for token, session in self._state.sessions.items()
            if now - session.last_active_at > max_idle_seconds
        ]
        if to_remove:
            for token in to_remove:
                del self._state.sessions[token]
            self.save()
            logger.info(f"Pruned {len(to_remove)} idle sessions")

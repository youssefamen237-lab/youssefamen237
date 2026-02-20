from datetime import datetime, timedelta, timezone
import random

from core.state import StateStore


class Scheduler:
    def __init__(self) -> None:
        self.state = StateStore()

    def due_short(self) -> bool:
        state = self.state.get()
        now = datetime.now(timezone.utc)
        if not state.get("last_short_at"):
            return True
        last = datetime.fromisoformat(state["last_short_at"])
        spacing = timedelta(hours=random.choice([4, 5, 6]))
        return now - last > spacing

    def due_long(self) -> bool:
        state = self.state.get()
        now = datetime.now(timezone.utc)
        if not state.get("last_long_at"):
            return True
        last = datetime.fromisoformat(state["last_long_at"])
        return now - last > timedelta(days=2)

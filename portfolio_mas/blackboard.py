from __future__ import annotations

import json
from pathlib import Path

from .models import Message


class Blackboard:
    """Append-only shared state; agents communicate through typed messages."""

    def __init__(self, audit_path: Path | None = None) -> None:
        self.messages: list[Message] = []
        self.audit_path = audit_path
        if audit_path:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text("")

    def publish(self, message: Message) -> None:
        self.messages.append(message)
        if self.audit_path:
            with self.audit_path.open("a") as handle:
                handle.write(json.dumps(message.to_dict(), sort_keys=True) + "\n")

    def by_correlation(self, correlation_id: str) -> list[Message]:
        return [m for m in self.messages if m.correlation_id == correlation_id]


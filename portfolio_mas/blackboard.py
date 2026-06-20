from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import Message, MessageType, Severity


class Blackboard:
    """Append-only shared state; agents communicate through typed messages."""

    ALLOWED_PARTICIPANTS = {
        "macro", "sector", "risk", "compliance", "portfolio_manager",
        "supervisor", "human_chair", "audit",
    }
    SENDER_MESSAGE_TYPES = {
        "macro": {MessageType.OBSERVATION},
        "sector": {MessageType.RECOMMENDATION},
        "risk": {MessageType.OBSERVATION, MessageType.CHALLENGE},
        "compliance": {MessageType.OBSERVATION, MessageType.VETO},
        "portfolio_manager": {MessageType.RECOMMENDATION},
        "supervisor": {MessageType.ESCALATION, MessageType.DECISION},
        "human_chair": {MessageType.APPROVAL},
        "audit": set(),
    }

    def __init__(self, audit_path: Path | None = None) -> None:
        self.messages: list[Message] = []
        self._ids: set[str] = set()
        self._inboxes: dict[str, list[Message]] = {
            participant: [] for participant in self.ALLOWED_PARTICIPANTS
        }
        self.audit_path = audit_path
        if audit_path:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.touch(exist_ok=True)

    def publish(self, message: Message) -> None:
        self._validate(message)
        self.messages.append(message)
        self._ids.add(message.id)
        for recipient in message.recipients:
            self._inboxes[recipient].append(message)
        if self.audit_path:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message.to_dict(), sort_keys=True) + "\n")

    def _validate(self, message: Message) -> None:
        if message.id in self._ids:
            raise ValueError(f"duplicate message id: {message.id}")
        if message.sender not in self.ALLOWED_PARTICIPANTS:
            raise ValueError(f"unknown sender: {message.sender}")
        if not isinstance(message.message_type, MessageType):
            raise ValueError("message_type must be a MessageType")
        if message.message_type not in self.SENDER_MESSAGE_TYPES[message.sender]:
            raise ValueError(
                f"sender {message.sender} cannot publish {message.message_type.value}"
            )
        if not isinstance(message.severity, Severity):
            raise ValueError("severity must be a Severity")
        if not isinstance(message.payload, dict):
            raise ValueError("payload must be an object")
        if not message.recipients:
            raise ValueError("message must have at least one recipient")
        unknown = set(message.recipients) - self.ALLOWED_PARTICIPANTS
        if unknown:
            raise ValueError(f"unknown recipients: {sorted(unknown)}")
        if not message.correlation_id.strip():
            raise ValueError("correlation_id is required")
        if not message.subject.strip():
            raise ValueError("subject is required")
        try:
            parsed = datetime.fromisoformat(message.timestamp)
        except ValueError as exc:
            raise ValueError("timestamp must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include a timezone")

    def by_correlation(self, correlation_id: str) -> list[Message]:
        return [m for m in self.messages if m.correlation_id == correlation_id]

    def for_recipient(self, recipient: str) -> list[Message]:
        if recipient not in self.ALLOWED_PARTICIPANTS:
            raise ValueError(f"unknown recipient: {recipient}")
        return list(self._inboxes[recipient])

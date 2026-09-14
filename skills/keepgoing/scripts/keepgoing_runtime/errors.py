"""Stable result and failure types used by the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUCCESS = 0
INVALID = 2
BLOCKED = 3
CONFLICT = 4
RECOVERY_REQUIRED = 5
IO_FAILURE = 6
CHECKPOINT_REQUIRED = 10


@dataclass(slots=True)
class KeepgoingError(Exception):
    """An expected runtime failure with a machine-stable exit code."""

    message: str
    code: int = INVALID
    result: str = "failure"
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def blocked(message: str, **details: Any) -> KeepgoingError:
    return KeepgoingError(message, BLOCKED, "blocked", details)


def conflict(message: str, **details: Any) -> KeepgoingError:
    return KeepgoingError(message, CONFLICT, "conflict", details)

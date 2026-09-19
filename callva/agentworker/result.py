"""What one turn hands back."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class FailureKind(StrEnum):
    QUOTA = "quota"
    MODEL_REFUSED = "model_refused"
    NOT_AUTHENTICATED = "not_authenticated"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BINARY_MISSING = "binary_missing"
    MAX_TURNS = "max_turns"
    BUDGET = "budget"
    INVALID_OUTPUT = "invalid_output"
    ERROR = "error"
    CRASH = "crash"


@dataclass(frozen=True)
class Failure:
    """A kind for code to branch on, and the engine's own sentence for a person."""

    kind: FailureKind
    message: str

    @property
    def retryable(self) -> bool:
        """True when running the same turn again later can succeed without any change."""
        return self.kind in (FailureKind.QUOTA, FailureKind.TIMEOUT, FailureKind.CRASH)


@dataclass(frozen=True)
class Tokens:
    input: int | None = None
    output: int | None = None
    cache_read: int | None = None
    cache_creation: int | None = None


@dataclass(frozen=True)
class Result:
    ok: bool
    engine: str
    answer: str = ""
    structured: Any = None
    session_id: str | None = None
    model: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    tokens: Tokens = field(default_factory=Tokens)
    permission_denials: tuple[dict, ...] = ()
    failure: Failure | None = None
    exit_code: int | None = None
    stderr_tail: str = ""
    command: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.failure is not None:
            data["failure"] = {"kind": str(self.failure.kind), "message": self.failure.message}
        data["permission_denials"] = list(self.permission_denials)
        data["command"] = list(self.command)
        return data

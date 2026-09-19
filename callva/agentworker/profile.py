"""How a turn is run, and which conversation it belongs to."""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

ENGINES = ("claude", "codex")
FENCES = ("read", "write", "act")

# Markers Claude Code sets in its own environment; a child claude that sees
# them believes it runs inside another session and behaves accordingly.
DEFAULT_DENY = ("CLAUDECODE", "CLAUDECODE_*", "CLAUDE_CODE_ENTRYPOINT")


class ProfileError(ValueError):
    """A profile that the schema refuses; the message names the path."""


def load_profile_schema() -> dict:
    with resources.files(__package__).joinpath("profile.schema.json").open("rb") as fh:
        return json.load(fh)


PROFILE_SCHEMA: dict = load_profile_schema()


def _matches(name: str, patterns) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


@dataclass(frozen=True)
class EnvPolicy:
    """Which inherited variables reach the engine.

    `allow` keeps only the named variables or globs when given; `deny` removes
    names or globs; `set` adds or overrides. Applied in that order.
    """

    allow: tuple[str, ...] | None = None
    deny: tuple[str, ...] = DEFAULT_DENY
    set: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.allow is not None:
            object.__setattr__(self, "allow", tuple(self.allow))
        object.__setattr__(self, "deny", tuple(self.deny))
        object.__setattr__(self, "set", dict(self.set))

    def apply(self, base: Mapping[str, str]) -> dict[str, str]:
        env: dict[str, str] = {}
        for key, value in base.items():
            if self.allow is not None and not _matches(key, self.allow):
                continue
            if _matches(key, self.deny):
                continue
            env[key] = value
        env.update(self.set)
        return env

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"deny": list(self.deny), "set": dict(self.set)}
        if self.allow is not None:
            data["allow"] = list(self.allow)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> EnvPolicy:
        data = dict(data or {})
        allow = data.get("allow")
        return cls(
            allow=tuple(allow) if allow is not None else None,
            deny=tuple(data.get("deny", DEFAULT_DENY)),
            set=dict(data.get("set", {})),
        )


@dataclass(frozen=True)
class Profile:
    engine: str
    fence: str = "read"
    model: str | None = None
    effort: str | None = None
    service_tier: str | None = None
    timeout_seconds: float = 600.0
    budget_usd: float | None = None
    allow_tools: tuple[str, ...] = ()
    env: EnvPolicy = field(default_factory=EnvPolicy)
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "allow_tools", tuple(self.allow_tools))
        object.__setattr__(self, "extra_args", tuple(self.extra_args))
        if isinstance(self.env, Mapping):
            object.__setattr__(self, "env", EnvPolicy.from_dict(self.env))
        validate_profile(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "fence": self.fence,
            "model": self.model,
            "effort": self.effort,
            "service_tier": self.service_tier,
            "timeout_seconds": self.timeout_seconds,
            "budget_usd": self.budget_usd,
            "allow_tools": list(self.allow_tools),
            "env": self.env.to_dict(),
            "extra_args": list(self.extra_args),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Profile:
        validate_profile(data)
        data = dict(data)
        return cls(
            engine=data["engine"],
            fence=data.get("fence", "read"),
            model=data.get("model"),
            effort=data.get("effort"),
            service_tier=data.get("service_tier"),
            timeout_seconds=float(data.get("timeout_seconds", 600.0)),
            budget_usd=data.get("budget_usd"),
            allow_tools=tuple(data.get("allow_tools", ())),
            env=EnvPolicy.from_dict(data.get("env")),
            extra_args=tuple(data.get("extra_args", ())),
        )


@dataclass(frozen=True)
class Session:
    """Which conversation a turn belongs to.

    `fresh` starts one; on claude the id is generated before launch and pinned,
    on codex it is learned from the stream. `pinned` lets the caller choose the
    id and is claude-only. `resume` continues an existing one on either engine.
    """

    kind: str = "fresh"
    id: str | None = None

    @classmethod
    def fresh(cls) -> Session:
        return cls("fresh", None)

    @classmethod
    def pinned(cls, session_id: str) -> Session:
        if not session_id:
            raise ValueError("a pinned session needs an id")
        return cls("pinned", session_id)

    @classmethod
    def resume(cls, session_id: str) -> Session:
        if not session_id:
            raise ValueError("a resumed session needs an id")
        return cls("resume", session_id)


_TYPES = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (Mapping,),
    "null": (type(None),),
}


def _type_ok(value: Any, kind: str) -> bool:
    if kind in ("number", "integer") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[kind])


def _validate(value: Any, schema: Mapping[str, Any], path: str) -> None:
    kinds = schema.get("type")
    if kinds is not None:
        allowed = kinds if isinstance(kinds, list) else [kinds]
        if not any(_type_ok(value, k) for k in allowed):
            expected = " or ".join(allowed)
            raise ProfileError(f"{path}: expected {expected}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise ProfileError(f"{path}: must be one of {schema['enum']}, got {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "exclusiveMinimum" in schema and not value > schema["exclusiveMinimum"]:
            raise ProfileError(f"{path}: must be greater than {schema['exclusiveMinimum']}")
        if "minimum" in schema and value < schema["minimum"]:
            raise ProfileError(f"{path}: must be at least {schema['minimum']}")
    if isinstance(value, Mapping):
        props = schema.get("properties", {})
        for name in schema.get("required", ()):
            if name not in value:
                raise ProfileError(f"{path}: missing required key {name!r}")
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                _validate(item, props[key], f"{path}.{key}")
            elif extra is False:
                raise ProfileError(f"{path}: unknown key {key!r}")
            elif isinstance(extra, Mapping):
                _validate(item, extra, f"{path}.{key}")
    if isinstance(value, (list, tuple)) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]")


def validate_profile(data: Mapping[str, Any]) -> None:
    """Raise ProfileError when `data` does not fit profile.schema.json."""
    if not isinstance(data, Mapping):
        raise ProfileError("profile: expected an object")
    _validate(data, PROFILE_SCHEMA, "profile")

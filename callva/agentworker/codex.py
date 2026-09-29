"""Codex through openai-codex: the thread a profile maps to, and the reading of the turn's stream.

The turn is read from `turn().stream()` rather than `thread.run()`, because
`run()` raises on a failed turn and drops `codexErrorInfo`, which is where
codex says whether a failure was a spent quota, a refused login or a budget.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openai_codex import ApprovalMode, Codex, CodexConfig, Thread

from .profile import Profile
from .result import FailureKind, Tokens

APPROVAL_MODES = {"never": ApprovalMode.deny_all, "auto_review": ApprovalMode.auto_review}

# codexErrorInfo values that name a failure kind on their own.
ERROR_INFO_KINDS = {
    "usageLimitExceeded": FailureKind.QUOTA,
    "rateLimitExceeded": FailureKind.QUOTA,
    "unauthorized": FailureKind.NOT_AUTHENTICATED,
    "sessionBudgetExceeded": FailureKind.BUDGET,
}


def config(profile: Profile, *, launcher: str, cwd: str, env: dict[str, str]) -> CodexConfig:
    """How the SDK starts codex: the launcher, the profile's extra arguments, then `app-server`."""
    args = (launcher, *profile.codex_extra_args, "app-server", "--listen", "stdio://")
    return CodexConfig(launch_args_override=args, cwd=cwd, env=env or None)


def thread_options(profile: Profile, *, cwd: str) -> dict[str, Any]:
    """The keyword arguments of `thread_start` and `thread_resume` a profile sets."""
    opts: dict[str, Any] = {"cwd": cwd}
    if profile.model:
        opts["model"] = profile.model
    if profile.codex_config:
        opts["config"] = dict(profile.codex_config)
    if profile.append_system_prompt:
        opts["developer_instructions"] = profile.append_system_prompt
    if profile.service_tier:
        opts["service_tier"] = profile.service_tier
    if profile.approval_policy:
        opts["approval_mode"] = APPROVAL_MODES[profile.approval_policy]
    return opts


def turn_options(profile: Profile) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    if profile.effort:
        opts["effort"] = profile.effort
    if profile.output_schema:
        opts["output_schema"] = dict(profile.output_schema)
    return opts


def _dump(obj: Any) -> Any:
    dump = getattr(obj, "model_dump", None)
    if dump is None:
        return obj
    return dump(mode="json", by_alias=True, exclude_none=True)


@dataclass
class Outcome:
    """Everything one codex turn produced, as the app-server reported it."""

    thread_id: str | None = None
    turn: dict | None = None
    items: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    usage_first: dict | None = None
    usage_last: dict | None = None
    error: BaseException | None = None
    stderr: tuple[str, ...] = ()


def run_turn(
    prompt: str,
    profile: Profile,
    *,
    cfg: CodexConfig,
    cwd: str,
    resume_id: str | None,
    outcome: Outcome,
    on_client: Callable[[Codex], None],
    on_event: Callable[[dict], None] | None,
) -> None:
    """Start codex, run one turn on a fresh or resumed thread, and read its stream."""
    client = None
    try:
        client = Codex(cfg)
        on_client(client)
        opts = thread_options(profile, cwd=cwd)
        if resume_id:
            thread: Thread = client.thread_resume(resume_id, **opts)
        else:
            thread = client.thread_start(**opts)
        outcome.thread_id = thread.id
        if profile.name:
            thread.set_name(profile.name)
        handle = thread.turn(prompt, **turn_options(profile))
        for event in handle.stream():
            params = _dump(event.payload)
            method = event.method
            if method == "item/completed" and isinstance(params, dict):
                outcome.items.append(params.get("item") or {})
            elif method == "thread/tokenUsage/updated" and isinstance(params, dict):
                usage = params.get("tokenUsage") or {}
                if outcome.usage_first is None:
                    outcome.usage_first = usage
                outcome.usage_last = usage
            elif method == "error" and isinstance(params, dict):
                outcome.errors.append(params)
            elif method == "turn/completed" and isinstance(params, dict):
                outcome.turn = params.get("turn") or {}
            if on_event is not None:
                # A caller's renderer never ends the turn.
                with contextlib.suppress(Exception):
                    on_event({"method": method, "params": params})
    except BaseException as exc:  # every ending is read, none is raised
        outcome.error = exc
    finally:
        if client is not None:
            inner = getattr(client, "_client", None)
            outcome.stderr = tuple(getattr(inner, "_stderr_lines", ()) or ())
            with contextlib.suppress(Exception):
                client.close()


def answer(outcome: Outcome) -> str:
    """The last agent message of the turn."""
    items = list(outcome.items)
    if outcome.turn and isinstance(outcome.turn.get("items"), list):
        items += outcome.turn["items"]
    for item in reversed(items):
        if isinstance(item, dict) and item.get("type") == "agentMessage" and item.get("text"):
            return str(item["text"])
    return ""


def tokens(outcome: Outcome) -> Tokens:
    """This turn's tokens: the thread's running total, less what it held before the turn."""
    last = outcome.usage_last or {}
    total = last.get("total") or {}
    if not total:
        return Tokens()
    first = outcome.usage_first or {}
    before = {}
    if first.get("total") and first.get("last"):
        before = {k: first["total"].get(k, 0) - first["last"].get(k, 0) for k in first["total"]}

    def count(key: str) -> int | None:
        value = total.get(key)
        return None if value is None else value - before.get(key, 0)

    return Tokens(input=count("inputTokens"), output=count("outputTokens"),
                  cache_read=count("cachedInputTokens"), cache_creation=None)


def turn_error(outcome: Outcome) -> dict | None:
    """The turn's own error, else the last fatal error event."""
    if outcome.turn and isinstance(outcome.turn.get("error"), dict):
        return outcome.turn["error"]
    for event in reversed(outcome.errors):
        if isinstance(event.get("error"), dict) and not event.get("willRetry"):
            return event["error"]
    return None


def error_info_kind(error: dict | None) -> tuple[FailureKind | None, int | None]:
    """The kind codexErrorInfo names, and the HTTP status it carries."""
    info = (error or {}).get("codexErrorInfo")
    if isinstance(info, str):
        return ERROR_INFO_KINDS.get(info), None
    if isinstance(info, dict):
        for value in info.values():
            if isinstance(value, dict) and isinstance(value.get("httpStatusCode"), int):
                return None, value["httpStatusCode"]
    return None, None

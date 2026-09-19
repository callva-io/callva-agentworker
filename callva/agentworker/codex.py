"""Codex CLI in exec mode: the command line, and the event stream."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .profile import Profile
from .result import Tokens

HOOK_TRUST_FLAG = "--dangerously-bypass-hook-trust"

# Lines codex prints on every run, fatal or not.
ROUTINE_STDERR = ("Reading additional input from stdin...",)


def fence_args(profile: Profile, *, hook_trust: bool) -> list[str]:
    # The sandbox flag is absent on `resume`; the config override works on both
    # the fresh and the resumed path and genuinely blocks writes.
    if profile.fence == "read":
        return ["-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"']
    if profile.fence == "write":
        return ["-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"']
    args = ["--dangerously-bypass-approvals-and-sandbox"]
    if hook_trust:
        args.append(HOOK_TRUST_FLAG)
    return args


def build_command(
    binary: str,
    profile: Profile,
    *,
    prompt: str,
    prompt_via: str,
    resume_id: str | None,
    schema_file: str | None,
    out_file: str,
    hook_trust: bool,
) -> list[str]:
    cmd = [binary, "exec"]
    if resume_id:
        cmd += ["resume", resume_id]
    cmd.append(prompt if prompt_via == "argv" else "-")
    cmd += ["--skip-git-repo-check", "--json", "-o", out_file]
    if profile.model:
        cmd += ["-m", profile.model]
    if profile.effort:
        cmd += ["-c", f'model_reasoning_effort="{profile.effort}"']
    if profile.service_tier:
        cmd += ["-c", f'model_service_tier="{profile.service_tier}"']
    if schema_file:
        cmd += ["--output-schema", schema_file]
    cmd += fence_args(profile, hook_trust=hook_trust)
    cmd += list(profile.extra_args)
    return cmd


@dataclass
class Parsed:
    thread_id: str | None = None
    usage: dict = field(default_factory=dict)
    failed: str | None = None
    errors: list[str] = field(default_factory=list)
    last_agent_message: str | None = None
    completed: bool = False
    events: list[dict] = field(default_factory=list)


def parse_events(stdout_lines: list[str]) -> Parsed:
    parsed = Parsed()
    for line in stdout_lines:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        parsed.events.append(event)
        kind = event.get("type")
        if kind == "thread.started":
            parsed.thread_id = event.get("thread_id") or parsed.thread_id
        elif kind == "turn.completed":
            parsed.completed = True
            usage = event.get("usage")
            if isinstance(usage, dict):
                parsed.usage = usage
        elif kind == "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else error
            if message:
                parsed.failed = str(message)
        elif kind == "error" and event.get("message"):
            parsed.errors.append(str(event["message"]))
        elif kind in ("item.completed", "item.started"):
            item = event.get("item")
            if isinstance(item, dict):
                if item.get("type") == "error" and item.get("message"):
                    parsed.errors.append(str(item["message"]))
                elif item.get("type") == "agent_message" and item.get("text") is not None:
                    parsed.last_agent_message = str(item["text"])
    return parsed


def failure_sentence(parsed: Parsed, stderr_tail: str, exit_code: int | None) -> str:
    """The order of authority: the turn's own verdict, a fatal event, then stderr."""
    for candidate in (parsed.failed, parsed.errors[-1] if parsed.errors else None):
        if candidate:
            return candidate
    residue = [line for line in stderr_tail.splitlines()
               if line.strip() and line.strip() not in ROUTINE_STDERR]
    if residue:
        return residue[-1].strip()
    return f"exit {exit_code}"


def tokens(parsed: Parsed) -> Tokens:
    usage = parsed.usage or {}
    return Tokens(
        input=usage.get("input_tokens"),
        output=usage.get("output_tokens"),
        cache_read=usage.get("cached_input_tokens"),
        cache_creation=None,
    )

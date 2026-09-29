"""The one verb: run a turn and hand back a Result."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import claude, codex, guard, tree
from .binaries import find_binary
from .classify import classify, unwrap_engine_message
from .launch import CLAUDE_SDK_OWNED, Launch, plan_env
from .profile import SESSION_MARKERS, Profile, Session
from .result import Failure, FailureKind, Result, Tokens

# How long a turn that was stopped may take to hand back what it had, once its
# processes are dead.
WIND_DOWN_SECONDS = 30.0


def _structured(answer: str, given: Any) -> tuple[Any, bool]:
    """The structured answer, and whether one was obtained."""
    if given is not None:
        return given, True
    text = answer.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text), True
        except ValueError:
            pass
    return None, False


def _unreported(error: BaseException | None, stderr: str) -> str:
    """What to say about a turn that ended without the engine's own report."""
    said = str(error).strip() if error is not None else ""
    lines = stderr.strip().splitlines()
    return said or (lines[-1] if lines else "the engine ended without a report")


def _tail(lines, count: int) -> str:
    return "\n".join(list(lines)[-count:]) if count > 0 else ""


class _Stopped:
    """How a supervised turn ended: on its own, by its deadline, or by the caller."""

    def __init__(self) -> None:
        self.timed_out = False
        self.cancelled = False

    @property
    def stopped(self) -> bool:
        return self.timed_out or self.cancelled


def _supervise(work: Callable[[], None], launch: Launch, *, timeout: float,
               cancel: threading.Event | None, on_stop: Callable[[], None]) -> _Stopped:
    """Run `work` on a thread and end it at the deadline or on cancel.

    Ending it means refusing any later engine start, killing every process the
    engine started, and then letting the SDK notice and unwind.
    """
    ending = _Stopped()
    worker = threading.Thread(target=work, name="agentworker-turn", daemon=True)
    worker.start()
    deadline = time.monotonic() + timeout
    while worker.is_alive():
        if cancel is not None and cancel.is_set():
            ending.cancelled = True
            break
        if time.monotonic() >= deadline:
            ending.timed_out = True
            break
        worker.join(0.05)
    if ending.stopped:
        tree.kill_tree(launch.stop())
        # The processes are already dead; this only lets the SDK notice sooner.
        with contextlib.suppress(Exception):
            on_stop()
        worker.join(WIND_DOWN_SECONDS)
    return ending


def run(
    prompt: str,
    profile: Profile,
    cwd: str | os.PathLike[str],
    *,
    session: Session | None = None,
    environ: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    on_event: Callable[[dict], None] | None = None,
    cancel: threading.Event | None = None,
    stderr_tail: int = 40,
) -> Result:
    """Run one headless turn and return what came of it.

    Never raises for anything the engine did; every ending is a Result. Raises
    ValueError only for a request the library cannot express, such as a pinned
    session on codex.

    `environ` is the environment the engine starts from (default: this
    process's); `extra_env` is set on top of it and of the profile's `env_set`.
    `on_event` receives one dict per engine event while the turn runs. Setting
    `cancel` ends the turn early and kills its processes.
    """
    session = session or Session.fresh()
    engine = profile.engine
    if engine == "codex" and session.kind == "pinned":
        raise ValueError("codex cannot pin a thread id; use Session.fresh() or Session.resume(id)")
    base = dict(os.environ if environ is None else environ)
    binary = profile.cli_path or find_binary(engine, base)
    if not binary or not os.access(binary, os.X_OK):
        where = f"at {binary}" if binary else "on PATH or in the usual places"
        return Result(ok=False, engine=engine, failure=Failure(
            FailureKind.BINARY_MISSING, f"no {engine} executable {where}"))
    verdict = guard.check(engine, binary, base)
    if verdict.refusal:
        return Result(ok=False, engine=engine, engine_version=verdict.version,
                      failure=Failure(FailureKind.INCOMPATIBLE_ENGINE, verdict.refusal))
    warnings = (verdict.warning,) if verdict.warning else ()
    markers = SESSION_MARKERS if profile.strip_session_markers else ()
    patterns = tuple(profile.env_remove) + markers
    plan = plan_env(inherited=os.environ, wanted_base=base,
                    set_env={**profile.env_set, **dict(extra_env or {})},
                    remove_patterns=patterns,
                    sdk_owned=CLAUDE_SDK_OWNED if engine == "claude" else ())
    # Codex finds its companion executables (the code-mode host that runs shell
    # commands) beside the path it was started from, so a symlinked install is
    # started at the file the link points to.
    launch = Launch(engine, os.path.realpath(binary) if engine == "codex" else binary, plan)
    context = {"engine_version": verdict.version, "warnings": warnings}
    workdir = str(Path(cwd))
    try:
        if engine == "claude":
            return _run_claude(prompt, profile, workdir, launch, plan.set, session, on_event,
                               cancel, stderr_tail, context)
        return _run_codex(prompt, profile, workdir, launch, plan.set, session, on_event,
                          cancel, stderr_tail, context)
    finally:
        launch.close()


def _stopped_failure(ending: _Stopped, profile: Profile) -> Failure:
    kind = classify(None, timed_out=ending.timed_out, cancelled=ending.cancelled)
    what = "cancelled" if ending.cancelled else f"timed out after {profile.timeout_seconds:g}s"
    return Failure(kind, f"turn {what}")


def _run_claude(prompt, profile, cwd, launch, env, session, on_event, cancel, stderr_tail,
                context) -> Result:
    resume_id = session.id if session.kind == "resume" else None
    session_id = session.id if session.kind == "pinned" else None
    if session.kind == "fresh":
        session_id = str(uuid.uuid4())
    outcome = claude.Outcome()
    opts = claude.options(profile, cli_path=str(launch.wrapper), cwd=cwd, env=env,
                          session_id=session_id, resume_id=resume_id,
                          stderr=outcome.stderr.append)
    started = time.monotonic()
    ending = _supervise(lambda: asyncio.run(claude.turn(prompt, opts, outcome, on_event)),
                        launch, timeout=profile.timeout_seconds, cancel=cancel,
                        on_stop=lambda: None)
    elapsed = int((time.monotonic() - started) * 1000)
    fields = claude.read(outcome.result) if outcome.result is not None else {}
    common = {
        "engine": "claude",
        "answer": fields.get("answer", ""),
        "session_id": fields.get("session_id") or session_id or resume_id,
        "model": fields.get("model") or (outcome.init or {}).get("model") or profile.model,
        "cost_usd": fields.get("cost_usd"),
        "duration_ms": fields.get("duration_ms") or elapsed,
        "num_turns": fields.get("num_turns"),
        "tokens": fields.get("tokens") or Tokens(),
        "permission_denials": fields.get("permission_denials", ()),
        "exit_code": getattr(outcome.error, "exit_code", None),
        "stderr_tail": _tail(outcome.stderr, stderr_tail),
        "command": launch.command(),
        "raw": claude.raw(outcome.result),
        **context,
    }
    if ending.stopped:
        retry = outcome.last_retry or {}
        status = retry.get("error_status")
        if ending.timed_out and status in (401, 429):
            message = (f"turn timed out after {profile.timeout_seconds:g}s while the engine "
                       f"retried: {retry.get('error')} (HTTP {status})")
            return Result(ok=False, failure=Failure(classify(message, http_status=status),
                                                    message), **common)
        return Result(ok=False, failure=_stopped_failure(ending, profile), **common)
    if outcome.result is None:
        error = outcome.error
        if type(error).__name__ == "CLINotFoundError":
            return Result(ok=False, failure=Failure(FailureKind.BINARY_MISSING, str(error)),
                          **common)
        message = _unreported(error, common["stderr_tail"])
        return Result(ok=False, failure=Failure(classify(message, had_report=False), message),
                      **common)
    ok = fields["subtype"] == "success" and not fields["is_error"]
    if not ok:
        status = fields.get("api_error_status")
        message = fields["answer"].strip() or common["stderr_tail"].strip() or \
            f"the turn ended with {fields['subtype']}"
        if status is not None and str(status) not in message:
            message = f"API error {status}: {message}"
        kind = classify(message, subtype=fields["subtype"], http_status=status)
        return Result(ok=False, failure=Failure(kind, message), **common)
    structured = None
    if profile.output_schema:
        structured, got = _structured(fields["answer"], fields.get("structured"))
        if not got:
            return Result(ok=False, failure=Failure(
                FailureKind.INVALID_OUTPUT, "a schema was required and the answer did not parse"),
                **common)
    return Result(ok=True, structured=structured, **common)


def _run_codex(prompt, profile, cwd, launch, env, session, on_event, cancel, stderr_tail,
               context) -> Result:
    resume_id = session.id if session.kind == "resume" else None
    outcome = codex.Outcome()
    cfg = codex.config(profile, launcher=str(launch.wrapper), cwd=cwd, env=env)
    clients: list = []
    started = time.monotonic()

    def work() -> None:
        codex.run_turn(prompt, profile, cfg=cfg, cwd=cwd, resume_id=resume_id, outcome=outcome,
                       on_client=clients.append, on_event=on_event)

    def unblock() -> None:
        for client in clients:
            client.close()

    ending = _supervise(work, launch, timeout=profile.timeout_seconds, cancel=cancel,
                        on_stop=unblock)
    elapsed = int((time.monotonic() - started) * 1000)
    answer = codex.answer(outcome)
    turn = outcome.turn or {}
    common = {
        "engine": "codex",
        "answer": answer,
        "session_id": outcome.thread_id or resume_id,
        "model": profile.model,
        "cost_usd": None,
        "duration_ms": turn.get("durationMs") or elapsed,
        "num_turns": None,
        "tokens": codex.tokens(outcome),
        "permission_denials": (),
        "exit_code": None,
        "stderr_tail": _tail(outcome.stderr, stderr_tail),
        "command": launch.command(),
        "raw": {"turn": outcome.turn, "items": outcome.items, "errors": outcome.errors},
        **context,
    }
    if ending.stopped:
        return Result(ok=False, failure=_stopped_failure(ending, profile), **common)
    if outcome.turn is None:
        error = outcome.error
        message = _unreported(error, common["stderr_tail"])
        return Result(ok=False, failure=Failure(classify(message, had_report=False), message),
                      **common)
    status = turn.get("status")
    error = codex.turn_error(outcome)
    if status == "completed" and error is None and answer:
        structured = None
        if profile.output_schema:
            structured, got = _structured(answer, None)
            if not got:
                return Result(ok=False, failure=Failure(
                    FailureKind.INVALID_OUTPUT,
                    "a schema was required and the answer did not parse"), **common)
        return Result(ok=True, structured=structured, **common)
    if error is not None:
        message = unwrap_engine_message(error.get("message")) or "the turn failed"
        kind, http_status = codex.error_info_kind(error)
        if kind is None:
            kind = classify(message, http_status=http_status)
        return Result(ok=False, failure=Failure(kind, message), **common)
    if status == "completed":
        return Result(ok=False, failure=Failure(
            FailureKind.ERROR, "the turn completed without a final message"), **common)
    return Result(ok=False, failure=Failure(FailureKind.ERROR, f"the turn ended {status}"),
                  **common)

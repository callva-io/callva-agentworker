"""The one verb: run a turn and hand back a Result."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import claude, codex
from .binaries import codex_supports, find_binary
from .classify import classify, unwrap_engine_message
from .process import run_process
from .profile import Profile, Session
from .result import Failure, FailureKind, Result, Tokens

PROMPT_PLACEHOLDER = "<prompt>"


def _try_json(line: str) -> dict | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        obj = json.loads(stripped)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _shown_command(cmd: list[str], prompt: str, prompt_via: str) -> tuple[str, ...]:
    if prompt_via != "argv":
        return tuple(cmd)
    return tuple(PROMPT_PLACEHOLDER if arg == prompt else arg for arg in cmd)


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


def run(
    prompt: str,
    profile: Profile,
    cwd: str | os.PathLike[str],
    *,
    session: Session | None = None,
    schema: Mapping[str, Any] | None = None,
    prompt_via: str = "stdin",
    environ: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    on_event: Callable[[dict], None] | None = None,
    cancel: threading.Event | None = None,
    name: str | None = None,
    stderr_tail: int = 40,
) -> Result:
    """Run one headless turn and return what came of it.

    Never raises for anything the engine did; every ending is a Result. Raises
    ValueError only for a request the library cannot express, such as a pinned
    session on codex.
    """
    if prompt_via not in ("stdin", "argv"):
        raise ValueError("prompt_via must be 'stdin' or 'argv'")
    session = session or Session.fresh()
    base = dict(os.environ if environ is None else environ)
    engine = profile.engine
    binary = find_binary(engine, base)
    if not binary:
        return Result(
            ok=False, engine=engine,
            failure=Failure(FailureKind.BINARY_MISSING,
                            f"no {engine} executable on PATH or in the usual places"),
        )
    env = profile.env.apply(base)
    if extra_env:
        env.update(dict(extra_env))
    workdir = str(Path(cwd))
    if engine == "claude":
        return _run_claude(prompt, profile, workdir, binary, env, session, schema, prompt_via,
                           on_event, cancel, name, stderr_tail)
    return _run_codex(prompt, profile, workdir, binary, env, session, schema, prompt_via,
                      on_event, cancel, stderr_tail)


def _run_claude(prompt, profile, cwd, binary, env, session, schema, prompt_via,
                on_event, cancel, name, stderr_tail) -> Result:
    resume_id = session.id if session.kind == "resume" else None
    session_id = None
    if session.kind == "pinned":
        session_id = session.id
    elif session.kind == "fresh":
        session_id = str(uuid.uuid4())
    schema_text = json.dumps(dict(schema)) if schema else None
    stream = on_event is not None
    cmd = claude.build_command(binary, profile, prompt=prompt, prompt_via=prompt_via,
                               session_id=session_id, resume_id=resume_id,
                               schema_text=schema_text, stream=stream, name=name)

    def on_line(line: str) -> None:
        doc = _try_json(line)
        if doc is not None and on_event is not None:
            on_event(doc)

    done = run_process(cmd, cwd=cwd, env=env,
                       stdin_text=prompt if prompt_via == "stdin" else None,
                       timeout=profile.timeout_seconds, cancel=cancel,
                       on_stdout_line=on_line if stream else None,
                       stderr_tail_lines=stderr_tail)
    doc = claude.result_document(done.stdout_lines)
    fields = claude.read(doc) if doc else {}
    known_id = fields.get("session_id") or session_id or resume_id
    shown = _shown_command(cmd, prompt, prompt_via)
    common = {
        "engine": "claude",
        "answer": fields.get("answer", ""),
        "session_id": known_id,
        "model": fields.get("model") or profile.model,
        "cost_usd": fields.get("cost_usd"),
        "duration_ms": fields.get("duration_ms") if fields else done.elapsed_ms,
        "num_turns": fields.get("num_turns"),
        "tokens": fields.get("tokens") or Tokens(),
        "permission_denials": fields.get("permission_denials", ()),
        "exit_code": done.exit_code,
        "stderr_tail": done.stderr_tail,
        "command": shown,
        "raw": doc or {},
    }
    if done.timed_out or done.cancelled:
        kind = classify(None, timed_out=done.timed_out, cancelled=done.cancelled)
        what = "cancelled" if done.cancelled else f"timed out after {profile.timeout_seconds:g}s"
        return Result(ok=False, failure=Failure(kind, f"turn {what}"), **common)
    if doc is None:
        message = done.stderr_tail.strip().splitlines()[-1] if done.stderr_tail.strip() \
            else f"exit {done.exit_code}"
        kind = classify(message, had_report=False)
        return Result(ok=False, failure=Failure(kind, message), **common)
    ok = fields["subtype"] == "success" and not fields["is_error"]
    if not ok:
        status = fields.get("api_error_status")
        message = fields["answer"].strip() or done.stderr_tail.strip() or f"exit {done.exit_code}"
        if status is not None and str(status) not in message:
            message = f"API error {status}: {message}"
        kind = classify(message, subtype=fields["subtype"], http_status=status)
        return Result(ok=False, failure=Failure(kind, message), **common)
    structured = None
    if schema:
        structured, got = _structured(fields["answer"], fields.get("structured"))
        if not got:
            return Result(ok=False, structured=None,
                          failure=Failure(FailureKind.INVALID_OUTPUT,
                                          "a schema was required and the answer did not parse"),
                          **common)
    return Result(ok=True, structured=structured, **common)


def _run_codex(prompt, profile, cwd, binary, env, session, schema, prompt_via,
               on_event, cancel, stderr_tail) -> Result:
    if session.kind == "pinned":
        raise ValueError("codex cannot pin a thread id; use Session.fresh() or Session.resume(id)")
    resume_id = session.id if session.kind == "resume" else None
    hook_trust = profile.fence == "act" and codex_supports(binary, codex.HOOK_TRUST_FLAG, env)
    out_fd, out_file = tempfile.mkstemp(prefix="agentworker-codex-", suffix=".txt")
    os.close(out_fd)
    schema_file = None
    try:
        if schema:
            s_fd, schema_file = tempfile.mkstemp(prefix="agentworker-schema-", suffix=".json")
            os.close(s_fd)
            Path(schema_file).write_text(json.dumps(dict(schema)))
        cmd = codex.build_command(binary, profile, prompt=prompt, prompt_via=prompt_via,
                                  resume_id=resume_id, schema_file=schema_file,
                                  out_file=out_file, hook_trust=hook_trust)

        def on_line(line: str) -> None:
            doc = _try_json(line)
            if doc is not None and on_event is not None:
                on_event(doc)

        done = run_process(cmd, cwd=cwd, env=env,
                           stdin_text=prompt if prompt_via == "stdin" else None,
                           timeout=profile.timeout_seconds, cancel=cancel,
                           on_stdout_line=on_line if on_event else None,
                           stderr_tail_lines=stderr_tail)
        parsed = codex.parse_events(done.stdout_lines)
        try:
            final = Path(out_file).read_text().strip()
        except OSError:
            final = ""
        answer = final or (parsed.last_agent_message or "").strip()
    finally:
        for path in (out_file, schema_file):
            if path:
                with contextlib.suppress(OSError):
                    os.unlink(path)
    shown = _shown_command(cmd, prompt, prompt_via)
    common = {
        "engine": "codex",
        "answer": answer,
        "session_id": parsed.thread_id or resume_id,
        "model": profile.model,
        "cost_usd": None,
        "duration_ms": done.elapsed_ms,
        "num_turns": None,
        "tokens": codex.tokens(parsed),
        "permission_denials": (),
        "exit_code": done.exit_code,
        "stderr_tail": done.stderr_tail,
        "command": shown,
        "raw": {"events": parsed.events, "final": final},
    }
    if done.timed_out or done.cancelled:
        kind = classify(None, timed_out=done.timed_out, cancelled=done.cancelled)
        what = "cancelled" if done.cancelled else f"timed out after {profile.timeout_seconds:g}s"
        return Result(ok=False, failure=Failure(kind, f"turn {what}"), **common)
    had_report = bool(parsed.events)
    ok = parsed.completed and parsed.failed is None and bool(answer) and done.exit_code == 0
    if not ok:
        message = unwrap_engine_message(codex.failure_sentence(parsed, done.stderr_tail,
                                                               done.exit_code))
        if parsed.completed and parsed.failed is None and not answer:
            message = "the turn completed without a final message"
        kind = classify(message, had_report=had_report)
        return Result(ok=False, failure=Failure(kind, message), **common)
    structured = None
    if schema:
        structured, got = _structured(answer, None)
        if not got:
            return Result(ok=False,
                          failure=Failure(FailureKind.INVALID_OUTPUT,
                                          "a schema was required and the answer did not parse"),
                          **common)
    return Result(ok=True, structured=structured, **common)

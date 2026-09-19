"""Run one child process under a deadline and a cancel, and kill its whole tree."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Completed:
    exit_code: int | None
    stdout_lines: list[str] = field(default_factory=list)
    stderr_tail: str = ""
    timed_out: bool = False
    cancelled: bool = False
    elapsed_ms: int = 0


def _kill_tree(proc: subprocess.Popen, grace_seconds: float) -> None:
    """SIGTERM the process group, wait, then SIGKILL what is left."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError, AttributeError):
        pgid = None
    if pgid is None:
        with contextlib.suppress(OSError):
            proc.kill()
        return
    for sig, wait in ((signal.SIGTERM, grace_seconds), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        if proc.poll() is not None:
            # The leader is gone; a second signal reaches any survivors of the group.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pgid, signal.SIGKILL)
            return


def run_process(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    stdin_text: str | None = None,
    timeout: float,
    cancel: threading.Event | None = None,
    on_stdout_line: Callable[[str], None] | None = None,
    stderr_tail_lines: int = 40,
    grace_seconds: float = 5.0,
) -> Completed:
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    stdout_lines: list[str] = []
    stderr_buf: deque[str] = deque(maxlen=stderr_tail_lines)

    def drain_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            stdout_lines.append(line)
            if on_stdout_line is not None:
                with contextlib.suppress(Exception):
                    on_stdout_line(line)

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_buf.append(line.rstrip("\n"))

    def feed_stdin() -> None:
        assert proc.stdin is not None
        try:
            proc.stdin.write(stdin_text or "")
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    threads = [threading.Thread(target=drain_stdout, daemon=True),
               threading.Thread(target=drain_stderr, daemon=True)]
    if stdin_text is not None:
        threads.append(threading.Thread(target=feed_stdin, daemon=True))
    for t in threads:
        t.start()

    deadline = started + timeout
    timed_out = cancelled = False
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
        time.sleep(0.05)
    if timed_out or cancelled:
        _kill_tree(proc, grace_seconds)
    proc.wait()
    for t in threads:
        t.join(timeout=2.0)
    exit_code = None if (timed_out or cancelled) else proc.returncode
    return Completed(
        exit_code=exit_code,
        stdout_lines=stdout_lines,
        stderr_tail="\n".join(stderr_buf),
        timed_out=timed_out,
        cancelled=cancelled,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )

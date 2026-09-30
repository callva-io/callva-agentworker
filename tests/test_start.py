import os
import subprocess
import sys

import pytest
from conftest import fake

from callva.harness_runner import FailureKind, Profile, Session, Started, run
from callva.harness_runner.launch import Launch, plan_env


def profile(harness: str, **knobs) -> Profile:
    return Profile(harness=harness, **{"cli_path": fake(harness), "timeout_seconds": 20, **knobs})


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Watch:
    """Records the order of on_start and on_event calls, and whether the pid was a live
    session leader when on_start ran."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.live: list[bool] = []

    def on_start(self, started: Started) -> None:
        self.live.append(alive(started.pid) and os.getsid(started.pid) == started.pid)
        self.calls.append(("start", started))

    def on_event(self, event: dict) -> None:
        self.calls.append(("event", event))

    @property
    def starts(self) -> list[Started]:
        return [c[1] for c in self.calls if c[0] == "start"]


def watched(harness, env, tmp_path, watch, **kw):
    return run("x", profile(harness), tmp_path, environ=env, on_event=watch.on_event,
               on_start=watch.on_start, **kw)


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_start_is_reported_once_before_any_event_with_the_pid_and_session(
        fake_env, record, tmp_path, harness):
    watch = Watch()
    result = watched(harness, fake_env, tmp_path, watch)
    assert result.ok, result.failure
    [started] = watch.starts
    assert watch.calls[0] == ("start", started) and len(watch.calls) > 1
    assert started.harness == harness
    assert started.session_id == result.session_id and started.session_id
    assert started.pid == record()["pid"] and watch.live == [True]


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_a_resumed_turn_reports_the_resumed_session(fake_env, record, tmp_path, harness):
    first = run("x", profile(harness), tmp_path, environ=fake_env)
    watch = Watch()
    again = watched(harness, fake_env, tmp_path, watch, session=Session.resume(first.session_id))
    assert again.ok, again.failure
    [started] = watch.starts
    assert started.session_id == first.session_id == again.session_id
    assert started.pid == record()["pid"] and watch.live == [True]


def test_a_pinned_claude_session_is_the_one_reported(fake_env, tmp_path):
    watch = Watch()
    pinned = "3f1f3a52-4f5e-4b8e-9d3a-7c1c2b3a4d5e"
    watched("claude", fake_env, tmp_path, watch, session=Session.pinned(pinned))
    assert [s.session_id for s in watch.starts] == [pinned]


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_no_start_is_reported_when_no_harness_runs(fake_env, tmp_path, harness):
    calls = []
    missing = run("x", profile(harness, cli_path=str(tmp_path / "absent")), tmp_path,
                  environ=fake_env, on_start=calls.append)
    assert missing.failure.kind == FailureKind.BINARY_MISSING
    assert calls == []


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_a_harness_stopped_before_it_starts_is_never_reported(tmp_path, harness):
    launch = Launch(harness, fake(harness), plan_env(inherited={}, wanted_base={}, set_env={},
                                                     remove_patterns=()))
    try:
        launch.stop()
        marker = "--input-format" if harness == "claude" else "app-server"
        done = subprocess.run([str(launch.wrapper), marker], capture_output=True, timeout=30,
                              env={"PATH": os.path.dirname(sys.executable) + ":/usr/bin:/bin"})
        assert done.returncode == 143
        assert launch.started() and launch.harness_pid() is None
    finally:
        launch.close()


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_a_failing_start_callback_changes_nothing(fake_env, tmp_path, harness):
    events = []

    def boom(started):
        raise RuntimeError("caller bug")

    result = run("x", profile(harness), tmp_path, environ=fake_env, on_event=events.append,
                 on_start=boom)
    plain = run("x", profile(harness), tmp_path, environ=fake_env)
    assert result.ok and result.answer == plain.answer and events

import importlib
import json
import os
import threading
import time
from pathlib import Path

import pytest
from conftest import fake

from callva.harness_runner import FailureKind, Profile, run
from callva.harness_runner.tree import find_tree

# The module, not the `run` function the package exports under the same name.
runner = importlib.import_module("callva.harness_runner.run")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def tree_pids(pid_file: str) -> list[int]:
    """The harness, its tool command, and everything the tool command started, found by
    the process group the tool command made for itself."""
    pids = json.loads(Path(pid_file).read_text())
    return [pids["harness"], *sorted(find_tree([pids["tool"]]))]


class TreeClock:
    """A stand-in for the library's clock that stands still until the fake harness has
    started its tree and written the pid file, then runs at real speed. The deadline
    therefore counts from the tree's existence, however long a loaded machine takes
    to get there. A tree that never appears lets the clock run after two minutes."""

    def __init__(self, pid_file: str) -> None:
        self.pid_file = pid_file
        self.origin = time.monotonic()
        self.tree_at: float | None = None

    def monotonic(self) -> float:
        now = time.monotonic()
        if self.tree_at is None:
            if not os.path.exists(self.pid_file) and now - self.origin < 120:
                return self.origin
            self.tree_at = now
        return self.origin + (now - self.tree_at)

    def __getattr__(self, name: str):
        return getattr(time, name)


def wait_for(path: str, seconds: float = 120.0) -> None:
    deadline = time.monotonic() + seconds
    while not os.path.exists(path) and time.monotonic() < deadline:
        time.sleep(0.05)


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_deadline_kills_the_whole_tree(fake_env, tmp_path, harness, monkeypatch):
    env = {**fake_env, f"FAKE_{harness.upper()}": "hang"}
    clock = TreeClock(fake_env["FAKE_PID_FILE"])
    monkeypatch.setattr(runner, "time", clock)
    seen: list[int] = []

    def watch():
        wait_for(fake_env["FAKE_PID_FILE"])
        time.sleep(0.3)
        seen.extend(tree_pids(fake_env["FAKE_PID_FILE"]))

    watcher = threading.Thread(target=watch)
    watcher.start()
    result = run("x", Profile(harness=harness, cli_path=fake(harness), timeout_seconds=3), tmp_path,
                 environ=env)
    watcher.join()
    assert clock.tree_at is not None, "the fake harness never started its tree"
    assert result.failure.kind == FailureKind.TIMEOUT
    assert "timed out after 3s" in result.failure.message
    # The harness ignores SIGTERM, so ending it took the SIGKILL after the grace period.
    assert time.monotonic() - clock.tree_at < 15
    # The harness, the tool shell, its background child and the double-forked grandchild.
    assert len(seen) >= 4, seen
    time.sleep(0.5)
    assert [p for p in seen if alive(p)] == []


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_cancel_ends_the_turn_and_kills_the_tree(fake_env, tmp_path, harness):
    env = {**fake_env, f"FAKE_{harness.upper()}": "hang"}
    cancel = threading.Event()
    seen: list[int] = []

    def later():
        wait_for(fake_env["FAKE_PID_FILE"])
        time.sleep(0.3)
        seen.extend(tree_pids(fake_env["FAKE_PID_FILE"]))
        cancel.set()

    threading.Thread(target=later).start()
    result = run("x", Profile(harness=harness, cli_path=fake(harness), timeout_seconds=180),
                 tmp_path, environ=env, cancel=cancel)
    assert result.failure.kind == FailureKind.CANCELLED
    time.sleep(0.5)
    assert seen and [p for p in seen if alive(p)] == []

import json
import os
import threading
import time
from pathlib import Path

import pytest
from conftest import fake

from callva.harness_runner import FailureKind, Profile, run
from callva.harness_runner.tree import find_tree


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


def wait_for(path: str, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not os.path.exists(path) and time.monotonic() < deadline:
        time.sleep(0.05)


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_deadline_kills_the_whole_tree(fake_env, tmp_path, harness):
    env = {**fake_env, f"FAKE_{harness.upper()}": "hang"}
    seen: list[int] = []

    def watch():
        wait_for(fake_env["FAKE_PID_FILE"])
        time.sleep(0.3)
        seen.extend(tree_pids(fake_env["FAKE_PID_FILE"]))

    watcher = threading.Thread(target=watch)
    watcher.start()
    started = time.monotonic()
    result = run("x", Profile(harness=harness, cli_path=fake(harness), timeout_seconds=3), tmp_path,
                 environ=env)
    watcher.join()
    assert result.failure.kind == FailureKind.TIMEOUT
    assert "timed out after 3s" in result.failure.message
    # The harness ignores SIGTERM, so ending it took the SIGKILL after the grace period.
    assert time.monotonic() - started < 15
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
    result = run("x", Profile(harness=harness, cli_path=fake(harness), timeout_seconds=60),
                 tmp_path, environ=env, cancel=cancel)
    assert result.failure.kind == FailureKind.CANCELLED
    time.sleep(0.5)
    assert seen and [p for p in seen if alive(p)] == []

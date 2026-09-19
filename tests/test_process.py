import os
import threading
import time

from callva.agentworker.process import run_process


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_gone(pid, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return not alive(pid)


def test_timeout_kills_the_whole_tree(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = ("import subprocess, time, sys; c = subprocess.Popen(['sleep','300']); "
              f"open({str(pid_file)!r},'w').write(str(c.pid)); sys.stdout.write('started\\n'); "
              "sys.stdout.flush(); time.sleep(300)")
    done = run_process(["python3", "-c", script], cwd=str(tmp_path), env=dict(os.environ),
                       timeout=1.0, grace_seconds=0.5)
    assert done.timed_out and not done.cancelled and done.exit_code is None
    assert done.stdout_lines == ["started"]
    child = int(pid_file.read_text())
    assert wait_gone(child), "the grandchild survived the kill"


def test_cancel_event_ends_the_turn(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    done = run_process(["sleep", "30"], cwd=str(tmp_path), env=dict(os.environ),
                       timeout=30.0, cancel=cancel, grace_seconds=0.5)
    assert done.cancelled and done.exit_code is None and done.elapsed_ms < 5000


def test_stdin_stdout_stderr_and_exit_code(tmp_path):
    script = ("import sys; d=sys.stdin.read(); print('got', len(d)); "
              "sys.stderr.write('e1\\ne2\\n'); sys.exit(3)")
    seen = []
    done = run_process(["python3", "-c", script], cwd=str(tmp_path), env=dict(os.environ),
                       stdin_text="x" * 5000, timeout=10.0, on_stdout_line=seen.append,
                       stderr_tail_lines=1)
    assert done.exit_code == 3 and done.stdout_lines == ["got 5000"] == seen
    assert done.stderr_tail == "e2"

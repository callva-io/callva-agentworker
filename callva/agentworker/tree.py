"""Kill everything an engine started, grandchildren included.

The launcher makes the engine a session leader. The engines put each tool
command in a process group of its own, and a command that backgrounds a child
and exits leaves that child with the group and session it was born in but a new
parent. So a tree is found three ways: by parentage from the engine, by the
process groups of what was found, and by the sessions of what was found; and
the caller's own group and session are never touched.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Iterable


def _table() -> list[tuple[int, int, int]]:
    """(pid, ppid, pgid) of every process visible to this user."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pgid="], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(p.lstrip("-").isdigit() for p in parts):
            rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return rows


def _sid(pid: int) -> int | None:
    try:
        return os.getsid(pid)
    except OSError:
        return None


def find_tree(roots: Iterable[int]) -> set[int]:
    """Every live process descended from `roots`, or sharing a group or session with one."""
    roots = {r for r in roots if r > 1}
    if not roots:
        return set()
    own_pgid, own_sid = os.getpgrp(), os.getsid(0)
    rows = _table()
    children: dict[int, list[int]] = {}
    pgid_of = {}
    for pid, ppid, pgid in rows:
        children.setdefault(ppid, []).append(pid)
        pgid_of[pid] = pgid
    found = set()
    stack = [r for r in roots if r in pgid_of]
    while stack:
        pid = stack.pop()
        if pid in found:
            continue
        found.add(pid)
        stack.extend(children.get(pid, ()))
    # A root is a session and group leader (the launcher made it one), so its id
    # names its session and group even after the root itself has died.
    groups = ({pgid_of[p] for p in found} | roots) - {own_pgid, 0, 1}
    sessions = ({s for s in (_sid(p) for p in found) if s is not None} | roots) - {own_sid, 0, 1}
    for pid, _ppid, pgid in rows:
        if pid in found or pid == os.getpid():
            continue
        if pgid in groups or _sid(pid) in sessions:
            found.add(pid)
    found |= {r for r in roots if _alive(r)}
    found.discard(os.getpid())
    return found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers signal 0; it is dead for this purpose.
    with contextlib.suppress(ChildProcessError, OSError):
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    return True


def kill_tree(roots: Iterable[int], grace_seconds: float = 3.0) -> set[int]:
    """SIGTERM the tree of `roots`, wait up to `grace_seconds`, SIGKILL what is left.

    Returns the pids that were found."""
    roots = set(roots)
    targets = find_tree(roots)
    if not targets:
        return set()
    _signal(roots, targets, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline and any(_alive(p) for p in targets):
        time.sleep(0.05)
    # Look again: a process can start a child between the snapshot and its death.
    survivors = {p for p in targets if _alive(p)} | (find_tree(roots) - targets)
    _signal(roots, survivors, signal.SIGKILL)
    return targets


def _signal(roots: set[int], pids: Iterable[int], sig: int) -> None:
    # Each root leads its own process group, so the group is signalled as well:
    # that still reaches its members where no process table could be read.
    for root in roots:
        if root > 1 and root != os.getpgrp():
            with contextlib.suppress(OSError):
                os.killpg(root, sig)
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, sig)

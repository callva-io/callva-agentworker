"""The launcher in front of the harness CLI: what it removes, and what it records."""

from __future__ import annotations

import contextlib
import json
import shlex
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

LAUNCHER = Path(__file__).with_name("_launcher.py")

# Variables the claude SDK sets for the CLI it starts. They are the SDK's own
# values, not inherited ones, so removal never touches them.
CLAUDE_SDK_OWNED = (
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_SDK_READS_SESSION_STATE",
    "PWD",
)

# The argument that marks the harness's own start, as opposed to a version probe
# the SDK runs through the same path first.
MARKERS = {"claude": "--input-format", "codex": "app-server"}


@dataclass(frozen=True)
class EnvPlan:
    """What the harness's environment is, split into what the SDK can express
    (values to set) and what only the launcher can (names to remove)."""

    set: dict[str, str]
    remove_names: tuple[str, ...]
    remove_patterns: tuple[str, ...]
    keep: tuple[str, ...]


def plan_env(
    *,
    inherited: Mapping[str, str],
    wanted_base: Mapping[str, str],
    set_env: Mapping[str, str],
    remove_patterns: Iterable[str],
    sdk_owned: Iterable[str] = (),
) -> EnvPlan:
    """The plan that turns `inherited` (what the SDK passes on) into `wanted_base`
    with `remove_patterns` removed and `set_env` set on top.

    Values travel through the SDK's own env option and never touch disk; the
    launcher only learns names.
    """
    keep = set(set_env) | set(sdk_owned)
    to_set = {k: v for k, v in wanted_base.items() if inherited.get(k) != v}
    to_set.update(set_env)
    remove_names = sorted(k for k in inherited if k not in wanted_base and k not in keep)
    return EnvPlan(set=to_set, remove_names=tuple(remove_names),
                   remove_patterns=tuple(remove_patterns), keep=tuple(sorted(keep)))


class Launch:
    """One turn's launcher: a private directory holding the wrapper, its spec,
    the record of what started, and the stop file."""

    def __init__(self, harness: str, binary: str, plan: EnvPlan) -> None:
        self.harness = harness
        self.dir = Path(tempfile.mkdtemp(prefix=f"harness-{harness}-"))
        self.pidfile = self.dir / "started.jsonl"
        self.stopfile = self.dir / "stop"
        self.specfile = self.dir / "spec.json"
        self.execfile = self.dir / "exec.jsonl"
        self.wrapper = self.dir / harness
        spec = {
            "binary": binary,
            "marker": MARKERS[harness],
            "keep": list(plan.keep),
            "remove_names": list(plan.remove_names),
            "remove_patterns": list(plan.remove_patterns),
            "pidfile": str(self.pidfile),
            "stop": str(self.stopfile),
            "exec": str(self.execfile),
        }
        self.specfile.write_text(json.dumps(spec))
        python = sys.executable or shutil.which("python3") or "python3"
        self.wrapper.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(python)} -I -S {shlex.quote(str(LAUNCHER))} "
            f"{shlex.quote(str(self.specfile))} \"$@\"\n"
        )
        self.wrapper.chmod(0o700)

    def started(self) -> list[dict]:
        """Every harness start the launcher recorded, oldest first."""
        try:
            lines = self.pidfile.read_text().splitlines()
        except OSError:
            return []
        records = []
        for line in lines:
            with contextlib.suppress(ValueError):
                records.append(json.loads(line))
        return records

    def harness_pid(self) -> int | None:
        """The pid of the first harness that passed the stop check and became the CLI."""
        try:
            lines = self.execfile.read_text().splitlines()
        except OSError:
            return None
        for line in lines:
            with contextlib.suppress(ValueError, KeyError, TypeError):
                return int(json.loads(line)["pid"])
        return None

    def stop(self) -> list[int]:
        """Refuse any later start, then name the harness processes that did start."""
        self.stopfile.touch()
        return [int(r["pid"]) for r in self.started() if "pid" in r]

    def command(self) -> tuple[str, ...]:
        records = self.started()
        return tuple(records[-1]["argv"]) if records else ()

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


__all__ = ["CLAUDE_SDK_OWNED", "EnvPlan", "Launch", "plan_env"]

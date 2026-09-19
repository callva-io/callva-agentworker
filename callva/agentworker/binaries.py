"""Find an engine outside a login shell, and ask it what it is."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

_FALLBACK_GLOBS = (
    "~/.local/bin",
    "~/.local/state/fnm_multishells/*/bin",
    "~/.fnm/node-versions/*/installation/bin",
    "~/.local/share/fnm/node-versions/*/installation/bin",
    "~/.nvm/versions/node/*/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)


def candidate_dirs(environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    dirs = [d for d in (env.get("PATH") or "").split(os.pathsep) if d]
    home = env.get("HOME") or os.path.expanduser("~")
    for pattern in _FALLBACK_GLOBS:
        expanded = pattern.replace("~", home, 1) if pattern.startswith("~") else pattern
        for path in sorted(glob.glob(expanded), reverse=True):
            if path not in dirs:
                dirs.append(path)
    return dirs


def find_binary(name: str, environ: Mapping[str, str] | None = None) -> str | None:
    for directory in candidate_dirs(environ):
        found = shutil.which(name, path=directory)
        if found:
            return found
    return None


@dataclass(frozen=True)
class Probe:
    engine: str
    found: bool
    path: str | None = None
    version: str | None = None
    error: str | None = None


def probe(engine: str, environ: Mapping[str, str] | None = None, timeout: float = 20.0) -> Probe:
    """Whether the engine is present, and what version answers."""
    path = find_binary(engine, environ)
    if not path:
        return Probe(engine, False, error=f"no {engine} executable on PATH or in the usual places")
    try:
        done = subprocess.run([path, "--version"], capture_output=True, text=True,
                              timeout=timeout,
                              env=dict(os.environ if environ is None else environ))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Probe(engine, True, path=path, error=str(exc))
    if done.returncode != 0:
        error = (done.stderr or done.stdout).strip()[-300:]
        return Probe(engine, True, path=path, error=error)
    version = (done.stdout or done.stderr).strip().splitlines()[0]
    return Probe(engine, True, path=path, version=version)


_support_cache: dict[tuple[str, str], bool] = {}


def codex_supports(binary: str, flag: str, environ: Mapping[str, str] | None = None) -> bool:
    """Whether this codex build knows `flag` on `exec`, read from its own help once."""
    key = (binary, flag)
    if key not in _support_cache:
        try:
            done = subprocess.run([binary, "exec", "--help"], capture_output=True, text=True,
                                  timeout=20.0,
                                  env=dict(os.environ if environ is None else environ))
            _support_cache[key] = flag in (done.stdout or "") + (done.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            _support_cache[key] = False
    return _support_cache[key]

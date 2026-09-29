import json
import os
import stat
import sys
from pathlib import Path

import pytest

FAKES = Path(__file__).parent / "fakes"


@pytest.fixture(scope="session", autouse=True)
def executable_fakes():
    for name in ("claude", "codex"):
        path = FAKES / name
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """The environment a turn starts from: the fakes are found first on PATH, the
    interpreter running the suite answers their `python3` shebang, and FAKE_RECORD
    names the file a fake writes its argv, environment and requests to."""
    path = os.pathsep.join([str(FAKES), os.path.dirname(sys.executable), "/usr/bin", "/bin"])
    monkeypatch.setenv("PATH", path)
    env = {
        "PATH": path,
        "HOME": str(tmp_path),
        "FAKE_RECORD": str(tmp_path / "record.json"),
        "FAKE_PID_FILE": str(tmp_path / "pids.json"),
    }
    for name in ("PYTHONPATH", "TMPDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


@pytest.fixture
def record(fake_env):
    """What the fake harness recorded about the turn it ran."""
    return lambda: json.loads(Path(fake_env["FAKE_RECORD"]).read_text())


def fake(harness: str) -> str:
    return str(FAKES / harness)

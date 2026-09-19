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
def fake_env(tmp_path):
    """An environment whose PATH holds only the fakes, plus a file the fakes record argv to."""
    argv_file = tmp_path / "argv.json"
    # The fakes are python scripts that spawn `sleep`, so the interpreter's own
    # directory and the system binaries sit behind the fakes on PATH.
    path = os.pathsep.join([str(FAKES), os.path.dirname(sys.executable), "/usr/bin", "/bin"])
    env = {
        "PATH": path,
        "HOME": str(tmp_path),
        "FAKE_ARGV_FILE": str(argv_file),
        "CLAUDECODE": "1",
        "KEEP_ME": "yes",
    }
    if "PYTHONPATH" in os.environ:
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    env["argv_file"] = str(argv_file)
    return env

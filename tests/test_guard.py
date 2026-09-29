import os

import pytest
from conftest import FAKES, fake

from callva.harness_runner import TESTED_VERSIONS, FailureKind, Profile, guard, probe, run


@pytest.fixture(autouse=True)
def fresh_cache():
    guard._cache.clear()
    yield
    guard._cache.clear()


VERSION_VAR = {"claude": "FAKE_CLAUDE_VERSION", "codex": "FAKE_CODEX_VERSION"}
SAY = {"claude": "{} (Claude Code)", "codex": "codex-cli {}"}


def bump(version: str, delta: int) -> str:
    major, minor, patch = (int(p) for p in version.split("."))
    if delta < 0 and patch == 0:
        return f"{major}.{minor - 1}.999"
    return f"{major}.{minor}.{patch + delta}"


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_older_than_tested_is_refused_naming_both_versions(fake_env, record, tmp_path, harness):
    low, _high = TESTED_VERSIONS[harness]
    old = bump(low, -1)
    env = {**fake_env, VERSION_VAR[harness]: SAY[harness].format(old)}
    result = run("x", Profile(harness=harness, cli_path=fake(harness)), tmp_path, environ=env)
    assert not result.ok and result.failure.kind == FailureKind.INCOMPATIBLE_HARNESS
    assert old in result.failure.message and low in result.failure.message
    assert result.harness_version == old
    assert not os.path.exists(fake_env["FAKE_RECORD"])  # no turn was started


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_newer_than_tested_runs_with_a_warning_naming_both(fake_env, tmp_path, harness):
    _low, high = TESTED_VERSIONS[harness]
    new = bump(high, 1)
    env = {**fake_env, VERSION_VAR[harness]: SAY[harness].format(new)}
    result = run("x", Profile(harness=harness, cli_path=fake(harness)), tmp_path, environ=env)
    assert result.ok and result.harness_version == new
    [warning] = result.warnings
    assert new in warning and high in warning


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_inside_the_range_runs_without_a_warning(fake_env, tmp_path, harness):
    for version in TESTED_VERSIONS[harness]:
        guard._cache.clear()
        env = {**fake_env, VERSION_VAR[harness]: SAY[harness].format(version)}
        result = run("x", Profile(harness=harness, cli_path=fake(harness)), tmp_path, environ=env)
        assert result.ok and result.warnings == () and result.harness_version == version


def test_an_unreadable_version_is_refused(fake_env, tmp_path):
    env = {**fake_env, "FAKE_CLAUDE_VERSION": "no version here"}
    result = run("x", Profile(harness="claude", cli_path=fake("claude")), tmp_path, environ=env)
    assert result.failure.kind == FailureKind.INCOMPATIBLE_HARNESS
    assert "could not read the version" in result.failure.message


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_a_missing_cli_keeps_its_own_failure(fake_env, tmp_path, harness):
    missing = run("x", Profile(harness=harness, cli_path=str(tmp_path / "nope")), tmp_path,
                  environ=fake_env)
    assert missing.failure.kind == FailureKind.BINARY_MISSING
    nowhere = run("x", Profile(harness=harness), tmp_path,
                  environ={**fake_env, "PATH": "/nonexistent", "HOME": str(tmp_path)})
    assert nowhere.failure.kind == FailureKind.BINARY_MISSING


def test_discovery_finds_the_installed_cli_on_path(fake_env, tmp_path):
    result = run("x", Profile(harness="claude"), tmp_path, environ=fake_env)
    assert result.ok and result.command[0] == str(FAKES / "claude")
    found = probe("codex", fake_env)
    assert found.found and found.path == str(FAKES / "codex") and "0.159.0" in found.version

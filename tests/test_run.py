import json
import os
import time

import pytest

from callva.agentworker import FailureKind, Profile, Session, probe, run


def argv_of(env):
    return json.loads(open(env["argv_file"]).read())


def test_claude_success_pins_session_and_reads_everything(fake_env, tmp_path):
    result = run("What is up?", Profile(engine="claude", fence="read", timeout_seconds=10),
                 cwd=tmp_path, environ=fake_env)
    assert result.ok and result.failure is None
    assert result.answer == "answer to: What is up?"
    argv = argv_of(fake_env)
    assert argv[argv.index("--session-id") + 1] == result.session_id
    assert result.model == "claude-fake-1" and result.cost_usd == 0.0123
    assert result.num_turns == 3 and result.duration_ms == 1234
    assert (result.tokens.input, result.tokens.cache_creation) == (100, 5)
    assert result.command[0].endswith("/claude") and result.exit_code == 0
    assert result.raw["type"] == "result"


def test_claude_env_policy_reaches_the_engine(fake_env, tmp_path):
    fake_env["FAKE_CLAUDE"] = "success"
    p = Profile(engine="claude", env={"deny": ["KEEP_ME"], "set": {"FAKE_CLAUDE": "quota"}})
    result = run("x", p, cwd=tmp_path, environ=fake_env)
    assert result.failure.kind == FailureKind.QUOTA


def test_claude_quota_auth_max_turns(fake_env, tmp_path):
    for mode, kind in (("quota", FailureKind.QUOTA), ("auth", FailureKind.NOT_AUTHENTICATED),
                       ("max_turns", FailureKind.MAX_TURNS)):
        result = run("x", Profile(engine="claude"), cwd=tmp_path,
                     environ={**fake_env, "FAKE_CLAUDE": mode})
        assert not result.ok and result.failure.kind == kind, mode
        assert result.session_id
    assert "usage limit" in run("x", Profile(engine="claude"), cwd=tmp_path,
                                environ={**fake_env, "FAKE_CLAUDE": "quota"}).failure.message


def test_claude_api_status_without_phrase_is_quota(fake_env, tmp_path):
    result = run("x", Profile(engine="claude"), cwd=tmp_path,
                 environ={**fake_env, "FAKE_CLAUDE": "api429"})
    assert result.failure.kind == FailureKind.QUOTA
    assert result.failure.message == "API error 429: API Error"


def test_claude_crash_and_missing_binary(fake_env, tmp_path):
    result = run("x", Profile(engine="claude"), cwd=tmp_path,
                 environ={**fake_env, "FAKE_CLAUDE": "crash"})
    assert result.failure.kind == FailureKind.CRASH and "frobnicate" in result.failure.message
    assert result.exit_code == 2
    missing = run("x", Profile(engine="claude"), cwd=tmp_path,
                  environ={"PATH": str(tmp_path), "HOME": str(tmp_path)})
    assert missing.failure.kind == FailureKind.BINARY_MISSING


def test_claude_structured_and_invalid_output(fake_env, tmp_path):
    schema = {"type": "object", "properties": {"verdict": {"type": "string"}}}
    good = run("x", Profile(engine="claude"), cwd=tmp_path, schema=schema,
               environ={**fake_env, "FAKE_CLAUDE": "structured"})
    assert good.ok and good.structured == {"verdict": "ok", "schema_seen": True}
    argv = argv_of(fake_env)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema
    bad = run("x", Profile(engine="claude"), cwd=tmp_path, schema=schema,
              environ={**fake_env, "FAKE_CLAUDE": "prose_under_schema"})
    assert bad.failure.kind == FailureKind.INVALID_OUTPUT and bad.answer == "just prose"


def test_claude_stream_events_and_resume_and_argv(fake_env, tmp_path):
    events = []
    result = run("stream me", Profile(engine="claude"), cwd=tmp_path, environ=fake_env,
                 session=Session.resume("old-1"), on_event=events.append, prompt_via="argv")
    assert result.ok and result.session_id == "old-1"
    assert [e.get("type") for e in events][:2] == ["system", "assistant"]
    assert any(e.get("type") == "result" for e in events)
    argv = argv_of(fake_env)
    assert argv[:2] == ["-p", "stream me"] and "--verbose" in argv
    assert argv[argv.index("--resume") + 1] == "old-1"
    assert "<prompt>" in result.command and "stream me" not in result.command


def test_claude_timeout_kills_tree_and_keeps_session(fake_env, tmp_path):
    pid_file = tmp_path / "child.pid"
    started = time.monotonic()
    result = run("x", Profile(engine="claude", timeout_seconds=1.0), cwd=tmp_path,
                 session=Session.pinned("pinned-1"),
                 environ={**fake_env, "FAKE_CLAUDE": "hang", "FAKE_PID_FILE": str(pid_file)})
    assert time.monotonic() - started < 15
    assert result.failure.kind == FailureKind.TIMEOUT and result.session_id == "pinned-1"
    assert result.exit_code is None
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("grandchild survived")


def test_codex_success_learns_thread_and_tokens(fake_env, tmp_path):
    result = run("Hello", Profile(engine="codex", fence="act"), cwd=tmp_path,
                 environ={**fake_env, "FAKE_CODEX_HOOKTRUST": "1"})
    assert result.ok and result.answer == "codex answer to: Hello"
    assert result.session_id == "thread-fake-1" and result.cost_usd is None
    assert (result.tokens.input, result.tokens.cache_read, result.tokens.output) == (300, 100, 40)
    argv = argv_of(fake_env)
    assert argv[:2] == ["exec", "-"] and "--dangerously-bypass-hook-trust" in argv
    assert result.raw["final"] == "codex answer to: Hello"


def test_codex_answer_from_stream_when_file_empty(fake_env, tmp_path):
    result = run("Hi", Profile(engine="codex"), cwd=tmp_path,
                 environ={**fake_env, "FAKE_CODEX": "no_file"})
    assert result.ok and result.answer == "codex answer to: Hi"


def test_codex_quota_crash_pinned(fake_env, tmp_path):
    quota = run("x", Profile(engine="codex"), cwd=tmp_path,
                environ={**fake_env, "FAKE_CODEX": "quota"})
    assert quota.failure.kind == FailureKind.QUOTA
    assert quota.failure.message == "Rate limit reached for gpt-fake: too many requests"
    assert quota.session_id == "thread-fake-1"
    crash = run("x", Profile(engine="codex"), cwd=tmp_path,
                environ={**fake_env, "FAKE_CODEX": "crash"})
    assert crash.failure.kind == FailureKind.ERROR and "panicked" in crash.failure.message
    with pytest.raises(ValueError):
        run("x", Profile(engine="codex"), cwd=tmp_path, session=Session.pinned("p"),
            environ=fake_env)


def test_codex_structured_and_resume(fake_env, tmp_path):
    result = run("x", Profile(engine="codex"), cwd=tmp_path, schema={"type": "object"},
                 session=Session.resume("thread-9"),
                 environ={**fake_env, "FAKE_CODEX": "structured"})
    assert result.ok and result.structured == {"verdict": "ok"} and result.session_id == "thread-9"
    argv = argv_of(fake_env)
    assert argv[:4] == ["exec", "resume", "thread-9", "-"] and "--output-schema" in argv


def test_probe_finds_fakes(fake_env):
    found = probe("codex", environ=fake_env)
    assert found.found and found.version == "codex-cli 0.0.0-fake"
    assert not probe("codex", environ={"PATH": "/nonexistent", "HOME": "/nonexistent"}).found

import pytest
from conftest import fake

from callva.agentworker import FailureKind, Profile, Session, run


def codex(**knobs) -> Profile:
    return Profile(engine="codex", **{"cli_path": fake("codex"), "timeout_seconds": 20, **knobs})


def requests(record, method):
    return [r["params"] for r in record()["requests"] if r["method"] == method]


def test_every_codex_knob_reaches_the_app_server(fake_env, record, tmp_path):
    config = {"default_permissions": "rf", "permissions": {"rf": {"extends": ":read-only",
                                                                  "network": {"enabled": True}}}}
    profile = codex(model="gpt-5.6-luna", effort="low", codex_config=config,
                    approval_policy="never", service_tier="flex", append_system_prompt="APPENDED",
                    output_schema={"type": "object"}, name="nightly",
                    codex_extra_args=["-c", "features.x=true", "--enable", "y"])
    result = run("hi", profile, tmp_path, environ={**fake_env, "FAKE_CODEX": "structured"})
    assert result.ok, result.failure
    rec = record()
    assert rec["argv"] == ["-c", "features.x=true", "--enable", "y",
                           "app-server", "--listen", "stdio://"]
    [start] = requests(record, "thread/start")
    assert start["model"] == "gpt-5.6-luna" and start["config"] == config
    assert start["approvalPolicy"] == "never" and start["serviceTier"] == "flex"
    assert start["developerInstructions"] == "APPENDED" and start["cwd"] == str(tmp_path)
    assert "baseInstructions" not in start
    [name] = requests(record, "thread/name/set")
    assert name["name"] == "nightly"
    [turn] = requests(record, "turn/start")
    assert turn["effort"] == "low" and turn["outputSchema"] == {"type": "object"}
    assert result.structured == {"verdict": "ok"}


def test_auto_review_and_default_approval(fake_env, record, tmp_path):
    assert run("x", codex(approval_policy="auto_review"), tmp_path, environ=fake_env).ok
    [start] = requests(record, "thread/start")
    assert start["approvalPolicy"] == "on-request" and start["approvalsReviewer"] == "auto_review"


def test_defaults_send_nothing_the_profile_did_not_name(fake_env, record, tmp_path):
    assert run("x", codex(), tmp_path, environ=fake_env).ok
    [start] = requests(record, "thread/start")
    assert set(start) <= {"cwd", "approvalPolicy", "approvalsReviewer"}
    [turn] = requests(record, "turn/start")
    assert "effort" not in turn and "outputSchema" not in turn


def test_success_reads_everything(fake_env, tmp_path):
    events = []
    result = run("What is up?", codex(model="gpt-x"), tmp_path, environ=fake_env,
                 on_event=events.append)
    assert result.ok and result.answer == "codex answer to: What is up?"
    assert result.session_id and result.model == "gpt-x" and result.cost_usd is None
    assert (result.tokens.input, result.tokens.output, result.tokens.cache_read) == (100, 20, 50)
    assert result.duration_ms == 3683 and result.engine_version == "0.159.0"
    assert result.raw["turn"]["status"] == "completed"
    assert events[-1]["method"] == "turn/completed"


def test_resume_continues_the_thread_and_counts_only_this_turn(fake_env, record, tmp_path):
    first = run("x", codex(), tmp_path, environ=fake_env)
    again = run("y", codex(append_system_prompt="A", codex_config={"sandbox_mode": "read-only"}),
                tmp_path, environ=fake_env, session=Session.resume(first.session_id))
    assert again.ok and again.session_id == first.session_id
    [resume] = requests(record, "thread/resume")
    assert resume["threadId"] == first.session_id
    assert resume["developerInstructions"] == "A"
    assert resume["config"] == {"sandbox_mode": "read-only"}
    assert requests(record, "thread/start") == []
    assert again.tokens.input == 100


def test_a_pinned_session_is_refused(fake_env, tmp_path):
    with pytest.raises(ValueError, match="codex cannot pin"):
        run("x", codex(), tmp_path, environ=fake_env, session=Session.pinned("abc"))


@pytest.mark.parametrize("mode,kind", [
    ("quota", FailureKind.QUOTA),
    ("unauthorized", FailureKind.NOT_AUTHENTICATED),
    ("badmodel", FailureKind.MODEL_REFUSED),
    ("http429", FailureKind.QUOTA),
    ("budget", FailureKind.BUDGET),
    ("empty", FailureKind.ERROR),
    ("crash", FailureKind.CRASH),
])
def test_failures_map_to_their_kind(fake_env, tmp_path, mode, kind):
    result = run("x", codex(), tmp_path, environ={**fake_env, "FAKE_CODEX": mode})
    assert not result.ok and result.failure.kind == kind, result.failure


def test_a_wrapped_provider_error_is_unwrapped(fake_env, tmp_path):
    result = run("x", codex(), tmp_path, environ={**fake_env, "FAKE_CODEX": "badmodel"})
    assert result.failure.message == (
        "The 'gpt-nonexistent-9' model is not supported when using Codex with a ChatGPT account.")


def test_structured_answer_that_does_not_parse(fake_env, tmp_path):
    result = run("x", codex(output_schema={"type": "object"}), tmp_path,
                 environ={**fake_env, "FAKE_CODEX": "prose_under_schema"})
    assert result.failure.kind == FailureKind.INVALID_OUTPUT and result.answer == "just prose"

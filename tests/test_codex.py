import json

from callva.agentworker import Profile
from callva.agentworker.codex import build_command, failure_sentence, parse_events, tokens


def cmd(profile, **kw):
    base = {"prompt": "hi", "prompt_via": "stdin", "resume_id": None, "schema_file": None,
            "out_file": "/tmp/out.txt", "hook_trust": False}
    base.update(kw)
    return build_command("/bin/codex", profile, **base)


def test_fresh_stdin_read_fence():
    p = Profile(engine="codex", fence="read", model="gpt-x", effort="high", service_tier="flex")
    c = cmd(p)
    assert c[:3] == ["/bin/codex", "exec", "-"]
    assert "--skip-git-repo-check" in c and "--json" in c and c[c.index("-o") + 1] == "/tmp/out.txt"
    assert c[c.index("-m") + 1] == "gpt-x"
    assert 'model_reasoning_effort="high"' in c and 'model_service_tier="flex"' in c
    assert 'sandbox_mode="read-only"' in c and 'approval_policy="never"' in c


def test_resume_argv_write_and_act():
    r = cmd(Profile(engine="codex", fence="write"), prompt="go", prompt_via="argv", resume_id="t1")
    assert r[:5] == ["/bin/codex", "exec", "resume", "t1", "go"]
    assert 'sandbox_mode="workspace-write"' in r
    a = cmd(Profile(engine="codex", fence="act", extra_args=("--color", "never")), hook_trust=True)
    assert "--dangerously-bypass-approvals-and-sandbox" in a
    assert "--dangerously-bypass-hook-trust" in a and a[-2:] == ["--color", "never"]
    b = cmd(Profile(engine="codex", fence="act"), hook_trust=False)
    assert "--dangerously-bypass-hook-trust" not in b


def test_schema_file_flag():
    c = cmd(Profile(engine="codex"), schema_file="/tmp/s.json")
    assert c[c.index("--output-schema") + 1] == "/tmp/s.json"


def test_parse_events_and_failure_order():
    lines = ["Reading additional input from stdin...",
             json.dumps({"type": "thread.started", "thread_id": "T"}),
             json.dumps({"type": "item.completed",
                         "item": {"type": "agent_message", "text": "hello"}}),
             json.dumps({"type": "error", "message": "transient"}),
             json.dumps({"type": "turn.failed", "error": {"message": "fatal one"}}),
             json.dumps({"type": "turn.completed",
                         "usage": {"input_tokens": 3, "cached_input_tokens": 1,
                                   "output_tokens": 2}})]
    parsed = parse_events(lines)
    assert parsed.thread_id == "T" and parsed.last_agent_message == "hello" and parsed.completed
    assert failure_sentence(parsed, "", 1) == "fatal one"
    parsed.failed = None
    assert failure_sentence(parsed, "", 1) == "transient"
    parsed.errors.clear()
    stderr = "Reading additional input from stdin...\nreal cause"
    assert failure_sentence(parsed, stderr, 1) == "real cause"
    assert failure_sentence(parsed, "Reading additional input from stdin...", 7) == "exit 7"
    t = tokens(parsed)
    assert (t.input, t.output, t.cache_read, t.cache_creation) == (3, 2, 1, None)

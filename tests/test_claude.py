import json

from callva.agentworker import Profile
from callva.agentworker.claude import build_command, documents, read, result_document


def cmd(profile, **kw):
    base = {"prompt": "hi", "prompt_via": "stdin", "session_id": None, "resume_id": None,
            "schema_text": None, "stream": False, "name": None}
    base.update(kw)
    return build_command("/bin/claude", profile, **base)


def test_read_fence_is_tools_plus_mcp_plus_plan():
    c = cmd(Profile(engine="claude", fence="read"))
    assert c[:4] == ["/bin/claude", "-p", "--output-format", "json"]
    assert c[c.index("--tools") + 1] == "Read,Glob,Grep"
    assert c[c.index("--permission-mode") + 1] == "plan"
    assert "--strict-mcp-config" in c and c[c.index("--mcp-config") + 1] == '{"mcpServers":{}}'


def test_read_fence_with_extras_adds_tool_and_uses_default_mode():
    c = cmd(Profile(engine="claude", fence="read", allow_tools=("Bash(tasks:*)", "Bash(gh:*)")))
    assert c[c.index("--tools") + 1] == "Read,Glob,Grep,Bash"
    assert c[c.index("--allowedTools") + 1] == "Read,Glob,Grep,Bash(tasks:*),Bash(gh:*)"
    assert c[c.index("--permission-mode") + 1] == "default"


def test_write_and_act_fences():
    w = cmd(Profile(engine="claude", fence="write", allow_tools=("Bash(pytest:*)",)))
    assert c_after(w, "--permission-mode") == "acceptEdits"
    assert c_after(w, "--allowedTools") == "Bash(pytest:*)"
    assert "--tools" not in w
    a = cmd(Profile(engine="claude", fence="act"))
    assert c_after(a, "--permission-mode") == "bypassPermissions"


def c_after(c, flag):
    return c[c.index(flag) + 1]


def test_session_schema_budget_stream_and_extras():
    p = Profile(engine="claude", model="m", effort="high", budget_usd=2.5, extra_args=("--x", "1"))
    c = cmd(p, session_id="sid", schema_text='{"type":"object"}', stream=True, name="w1")
    assert c_after(c, "--output-format") == "stream-json" and "--verbose" in c
    assert c_after(c, "--model") == "m" and c_after(c, "--effort") == "high"
    assert c_after(c, "--session-id") == "sid" and c_after(c, "--name") == "w1"
    assert c_after(c, "--max-budget-usd") == "2.5"
    assert c_after(c, "--json-schema") == '{"type":"object"}'
    assert c[-2:] == ["--x", "1"]
    r = cmd(p, session_id="sid", resume_id="old")
    assert "--resume" in r and "--session-id" not in r


def test_prompt_via_argv():
    c = cmd(Profile(engine="claude"), prompt="do it", prompt_via="argv")
    assert c[:3] == ["/bin/claude", "-p", "do it"]


def test_documents_tolerate_hook_noise_and_pretty_json():
    lines = [json.dumps({"hook": "x"}),
             json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "A",
                         "session_id": "s", "modelUsage": {"m1": {"outputTokens": 1},
                                                           "m2": {"outputTokens": 9}}}),
             "{", '  "hook": "after",', '  "nested": {"a": [1, 2]}', "}"]
    docs = documents(lines)
    assert [d.get("hook") for d in docs if "hook" in d] == ["x", "after"]
    doc = result_document(lines)
    assert doc["result"] == "A"
    fields = read(doc)
    assert fields["model"] == "m2" and fields["answer"] == "A" and fields["subtype"] == "success"


def test_result_document_without_type_key():
    lines = [json.dumps({"result": "B", "is_error": True, "subtype": "success"})]
    assert result_document(lines)["result"] == "B"
    assert result_document(["plain text", "not json"]) is None

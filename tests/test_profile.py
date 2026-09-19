import pytest

from callva.agentworker import DEFAULT_DENY, EnvPolicy, Profile, ProfileError, Session


def test_from_dict_roundtrip():
    data = {"engine": "codex", "fence": "act", "model": "gpt-x", "effort": "high",
            "timeout_seconds": 30, "allow_tools": ["Bash(tasks:*)"], "add_dirs": ["/srv/x"],
            "env": {"deny": ["SECRET_*"], "set": {"A": "1"}}, "extra_args": ["--flag"]}
    profile = Profile.from_dict(data)
    assert profile.engine == "codex" and profile.fence == "act"
    assert profile.allow_tools == ("Bash(tasks:*)",) and profile.add_dirs == ("/srv/x",)
    assert profile.env.deny == ("SECRET_*",) and profile.env.set == {"A": "1"}
    again = Profile.from_dict(profile.to_dict())
    assert again == profile


@pytest.mark.parametrize("bad", [
    {"engine": "gemini"},
    {"engine": "claude", "fence": "rw"},
    {"engine": "claude", "timeout_seconds": 0},
    {"engine": "claude", "budget_usd": -1},
    {"engine": "claude", "colour": "blue"},
    {"engine": "claude", "env": {"allow": "PATH"}},
    {"engine": "claude", "timeout_seconds": True},
    {},
])
def test_schema_refuses(bad):
    with pytest.raises(ProfileError):
        Profile.from_dict(bad)


def test_constructor_validates_too():
    with pytest.raises(ProfileError):
        Profile(engine="claude", fence="everything")


def test_env_policy_default_drops_nested_markers():
    env = EnvPolicy().apply({"PATH": "/x", "CLAUDECODE": "1", "CLAUDECODE_FOO": "2",
                             "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_USE_BEDROCK": "1"})
    assert env == {"PATH": "/x", "CLAUDE_CODE_USE_BEDROCK": "1"}
    assert DEFAULT_DENY == ("CLAUDECODE", "CLAUDECODE_*", "CLAUDE_CODE_ENTRYPOINT")


def test_env_policy_allow_deny_set_order():
    policy = EnvPolicy(allow=("PATH", "APP_*"), deny=("APP_SECRET",), set={"APP_MODE": "test"})
    env = policy.apply({"PATH": "/x", "APP_ONE": "1", "APP_SECRET": "s", "HOME": "/h"})
    assert env == {"PATH": "/x", "APP_ONE": "1", "APP_MODE": "test"}


def test_session_kinds():
    assert Session.fresh().kind == "fresh"
    assert Session.pinned("abc").id == "abc"
    assert Session.resume("abc").kind == "resume"
    with pytest.raises(ValueError):
        Session.pinned("")

import json
from pathlib import Path

import pytest

from callva.harness_runner import (
    Profile,
    ProfileError,
    ProfileNotFound,
    find_profile,
    find_profile_file,
    list_profiles,
    machine_folder,
)
from callva.harness_runner.__main__ import main
from callva.harness_runner.discovery import shipped_folder

SHIPPED = ("act", "read", "read-sandboxed")
READ_ONLY = ("This is a READ-ONLY research query. Change nothing: no file writes or edits, no "
             "commits, and no state changes in this project or in any system you reach. Read, "
             "run read-only commands, and answer.")


def write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.toml"
    path.write_text(text)
    return path


def table(harness: str, model: str) -> str:
    return f'[{harness}]\nmodel = "{model}"\n'


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """An isolated machine folder, through XDG_CONFIG_HOME."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "callva-harness-runner" / "profiles"


def test_the_machine_folder_follows_xdg_and_falls_back_to_dot_config(tmp_path):
    assert machine_folder({"XDG_CONFIG_HOME": "/cfg", "HOME": "/h"}) == Path(
        "/cfg/callva-harness-runner/profiles")
    for unset in ({}, {"XDG_CONFIG_HOME": ""}, {"XDG_CONFIG_HOME": "relative"}):
        assert machine_folder({**unset, "HOME": "/h"}) == Path(
            "/h/.config/callva-harness-runner/profiles")


def test_sources_are_searched_folders_first_then_machine_then_shipped(tmp_path, machine):
    first, second = tmp_path / "first", tmp_path / "second"
    assert find_profile("read", "claude", [first, second]).model == "claude-opus-5-5"  # shipped
    write(machine, "read", table("claude", "from-machine"))
    assert find_profile("read", "claude", [first, second]).model == "from-machine"
    write(second, "read", table("claude", "from-second"))
    assert find_profile("read", "claude", [first, second]).model == "from-second"
    write(first, "read", table("claude", "from-first"))
    found = find_profile_file("read", [first, second])
    assert (found.source, found.path) == ("folder", str(first / "read.toml"))
    assert found.profile("claude").model == "from-first"
    assert found.shadows == (str(second / "read.toml"), str(machine / "read.toml"),
                             str(shipped_folder().joinpath("read.toml")))
    assert find_profile("read", "claude").model == "from-machine"
    assert find_profile_file("read").source == "machine"


def test_the_found_file_is_used_whole_without_falling_through(tmp_path, machine):
    folder = tmp_path / "mine"
    path = write(folder, "act", table("codex", "gpt-x"))
    assert find_profile("act", "codex", [folder]).model == "gpt-x"
    with pytest.raises(ProfileError) as refused:
        find_profile("act", "claude", [folder])
    message = str(refused.value)
    assert str(path) in message and "[claude]" in message
    # No merging: knobs the shipped act sets are absent from the found file's table.
    assert find_profile("act", "codex", [folder]).timeout_seconds == 600.0


def test_the_harness_key_may_be_omitted_and_must_match_when_present(tmp_path, machine):
    folder = tmp_path / "mine"
    write(folder, "ok", '[claude]\nharness = "claude"\nmodel = "m"\n')
    assert find_profile("ok", "claude", [folder]).harness == "claude"
    path = write(folder, "bad", '[claude]\nharness = "codex"\n[codex]\n')
    with pytest.raises(ProfileError, match="the table name is the harness") as refused:
        find_profile("bad", "claude", [folder])
    assert str(path) in str(refused.value)


def test_a_file_holds_only_harness_tables_and_valid_knobs(tmp_path, machine):
    folder = tmp_path / "mine"
    write(folder, "extra", 'model = "x"\n[claude]\n')
    with pytest.raises(ProfileError, match="not a harness table"):
        find_profile("extra", "claude", [folder])
    write(folder, "gemini", "[gemini]\n")
    with pytest.raises(ProfileError, match="'gemini' is not a harness table"):
        find_profile("gemini", "claude", [folder])
    write(folder, "broken", "[claude\n")
    with pytest.raises(ProfileError, match="not valid TOML"):
        find_profile("broken", "claude", [folder])
    write(folder, "old", '[claude]\nengine = "claude"\n')
    with pytest.raises(ProfileError, match="'engine' was renamed 'harness'"):
        find_profile("old", "claude", [folder])
    write(folder, "wrong", '[codex]\npermission_mode = "plan"\n')
    with pytest.raises(ProfileError, match="codex cannot honour it"):
        find_profile("wrong", "codex", [folder])


@pytest.mark.parametrize("name", ["../read", "a/b", ".hidden", "", "x" * 65, "a..b", "read.toml/",
                                  "~root", "a b"])
def test_unsafe_names_are_refused(tmp_path, machine, name):
    with pytest.raises(ProfileError, match="is not allowed"):
        find_profile(name, "claude", [tmp_path])


def test_an_unknown_name_is_not_found(machine):
    with pytest.raises(ProfileNotFound, match="no profile named 'nope'"):
        find_profile("nope", "claude")


def test_the_listing_shows_every_visible_profile_and_what_it_shadows(tmp_path, machine):
    folder = tmp_path / "mine"
    write(folder, "read", table("claude", "mine"))
    write(folder, "solo", table("codex", "x"))
    write(machine, "read", table("codex", "machine"))
    write(machine, "broken", "[claude\n")
    (folder / "notes.txt").write_text("not a profile")
    (folder / ".hidden.toml").write_text("[claude]\n")
    listing = {entry.name: entry for entry in list_profiles([folder])}
    assert sorted(listing) == ["act", "broken", "read", "read-sandboxed", "solo"]
    read = listing["read"]
    assert (read.source, read.path, read.harnesses) == ("folder", str(folder / "read.toml"),
                                                      ("claude",))
    assert read.shadows == (str(machine / "read.toml"),
                            str(shipped_folder().joinpath("read.toml")))
    assert listing["solo"].harnesses == ("codex",) and listing["solo"].shadows == ()
    assert listing["act"].source == "shipped" and listing["act"].harnesses == ("claude", "codex")
    assert listing["broken"].harnesses == () and "not valid TOML" in listing["broken"].error
    assert "error" not in read.to_dict() and read.to_dict()["shadows"] == list(read.shadows)


@pytest.mark.parametrize("name", SHIPPED)
@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_each_shipped_profile_loads_on_both_harnesses(machine, name, harness):
    profile = find_profile(name, harness)
    assert isinstance(profile, Profile) and profile.harness == harness
    assert profile.model == {"claude": "claude-opus-5-5", "codex": "gpt-6-sol"}[harness]
    assert profile.effort == "medium" and profile.timeout_seconds == 3600
    assert find_profile_file(name).source == "shipped"


def test_shipped_read_is_held_by_instruction_only(machine):
    claude, codex = find_profile("read", "claude"), find_profile("read", "codex")
    assert claude.permission_mode == "bypassPermissions" and claude.settings is None
    assert claude.setting_sources == ("project", "local") and claude.tools is None
    # No settings at all, so the target's hooks run.
    assert codex.codex_config == {"sandbox_mode": "danger-full-access"}
    for profile in (claude, codex):
        assert profile.append_system_prompt == READ_ONLY
        assert profile.env_set == {"CAPABILITIES_READ_ONLY": "1"}


def test_shipped_act_has_full_access(machine):
    claude, codex = find_profile("act", "claude"), find_profile("act", "codex")
    assert claude.permission_mode == "bypassPermissions" and claude.setting_sources is None
    assert codex.approval_policy == "never"
    assert codex.codex_config == {"sandbox_mode": "danger-full-access"}
    assert claude.env_set == {} and "full write access" in claude.append_system_prompt


def test_shipped_read_sandboxed_is_enforced_by_the_os(machine):
    claude = find_profile("read-sandboxed", "claude")
    codex = find_profile("read-sandboxed", "codex")
    sandbox = claude.settings["sandbox"]
    assert sandbox["enabled"] and sandbox["failIfUnavailable"]
    assert sandbox["autoAllowBashIfSandboxed"]
    assert sandbox["allowUnsandboxedCommands"] is False
    assert sandbox["filesystem"] == {"allowWrite": ["~/.cache"]}
    assert sandbox["network"] == {"allowedDomains": ["*"]}
    # A hook runs outside the sandbox and could write the target.
    assert claude.settings["disableAllHooks"] is True
    permissions = claude.settings["permissions"]
    assert "Edit(./**)" in permissions["deny"] and permissions["ask"] == ["Bash"]
    assert claude.disallowed_tools == ("Write", "Edit", "NotebookEdit")
    assert claude.setting_sources == ("project", "local") and claude.permission_mode == "default"
    assert claude.strict_mcp and claude.mcp_config == {"mcpServers": {}}
    assert codex.codex_config == {
        "default_permissions": "read-sandboxed",
        "permissions": {"read-sandboxed": {
            "extends": ":read-only",
            "filesystem": {"~/.cache": "write", ":tmpdir": "write"},
            "network": {"enabled": True}}}}
    for profile in (claude, codex):
        assert profile.append_system_prompt == READ_ONLY
        assert profile.env_set == {"CAPABILITIES_READ_ONLY": "1"}


def test_the_cli_lists_and_shows(tmp_path, machine, capsys):
    folder = tmp_path / "mine"
    path = write(folder, "read", table("claude", "mine"))
    assert main(["profiles", "--folder", str(folder)]) == 0
    listing = {e["name"]: e for e in json.loads(capsys.readouterr().out)}
    assert listing["read"]["source"] == "folder" and listing["read"]["path"] == str(path)
    assert len(listing["read"]["shadows"]) == 1 and listing["act"]["source"] == "shipped"
    assert main(["profiles", "show", "read", "--folder", str(folder)]) == 0
    assert capsys.readouterr().out == f"# folder: {path}\n" + table("claude", "mine")
    assert main(["profiles", "show", "read-sandboxed"]) == 0
    shown = capsys.readouterr().out
    assert shown.startswith("# shipped: ") and "Edit(./**)" in shown
    assert main(["profiles", "show", "../x"]) == 2
    assert "is not allowed" in capsys.readouterr().err

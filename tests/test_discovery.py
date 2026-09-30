import json
import re
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

SHIPPED = ("claude-act", "claude-read", "claude-read-sandboxed",
           "codex-act", "codex-read", "codex-read-sandboxed")
READ_ONLY = ("This is a READ-ONLY research query. Change nothing: no file writes or edits, no "
             "commits, and no state changes in this project or in any system you reach. Read, "
             "run read-only commands, and answer.")
FLAT_FORM = 'a profile file is flat: `harness = "claude"` or `harness = "codex"` at the top'


def write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.toml"
    path.write_text(text)
    return path


def flat(harness: str, model: str) -> str:
    return f'harness = "{harness}"\nmodel = "{model}"\n'


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
    name = "claude-read"
    assert find_profile(name, [first, second]).model == "opus"  # shipped
    write(machine, name, flat("claude", "from-machine"))
    assert find_profile(name, [first, second]).model == "from-machine"
    write(second, name, flat("claude", "from-second"))
    assert find_profile(name, [first, second]).model == "from-second"
    write(first, name, flat("codex", "from-first"))
    found = find_profile_file(name, [first, second])
    assert (found.source, found.path) == ("folder", str(first / f"{name}.toml"))
    # The first file is used whole, whatever harness it names.
    assert found.harness == "codex" and found.profile().harness == "codex"
    assert found.profile().model == "from-first"
    assert found.shadows == (str(second / f"{name}.toml"), str(machine / f"{name}.toml"),
                             str(shipped_folder().joinpath(f"{name}.toml")))
    assert find_profile(name).model == "from-machine"
    assert find_profile_file(name).source == "machine"


def test_the_found_file_is_used_whole_without_falling_through(tmp_path, machine):
    folder = tmp_path / "mine"
    write(folder, "codex-act", flat("codex", "gpt-x"))
    profile = find_profile("codex-act", [folder])
    assert profile.model == "gpt-x"
    # No merging: knobs the shipped codex-act sets are absent from the found file.
    assert profile.timeout_seconds == 600.0 and profile.approval_policy is None
    path = write(folder, "claude-act", "[claude\n")
    with pytest.raises(ProfileError, match="not valid TOML") as refused:
        find_profile("claude-act", [folder])
    assert str(path) in str(refused.value)


@pytest.mark.parametrize("text", [
    '[claude]\nmodel = "m"\n',
    '[codex]\nmodel = "m"\n',
    '[claude]\nmodel = "m"\n[codex]\nmodel = "n"\n',
    '[claude]\nharness = "claude"\n',
    'harness = "claude"\n[claude]\nmodel = "m"\n',
])
def test_a_file_with_harness_tables_is_refused_naming_the_flat_form(tmp_path, machine, text):
    path = write(tmp_path, "old", text)
    for load in (lambda: find_profile("old", [tmp_path]),
                 lambda: find_profile_file("old", [tmp_path]).profile(),
                 lambda: find_profile_file("old", [tmp_path]).harness):
        with pytest.raises(ProfileError) as refused:
            load()
        message = str(refused.value)
        assert str(path) in message and "harness table" in message
        assert "0.5.0" in message and FLAT_FORM in message


@pytest.mark.parametrize("text", ['model = "m"\n', "", '[settings]\ndisableAllHooks = true\n'])
def test_a_file_without_a_top_level_harness_is_refused_naming_the_flat_form(
        tmp_path, machine, text):
    path = write(tmp_path, "bare", text)
    with pytest.raises(ProfileError) as refused:
        find_profile("bare", [tmp_path])
    message = str(refused.value)
    assert str(path) in message and "no top-level `harness`" in message
    assert FLAT_FORM in message


def test_a_file_holds_one_harness_and_valid_knobs(tmp_path, machine):
    folder = tmp_path / "mine"
    write(folder, "gemini", 'harness = "gemini"\n')
    with pytest.raises(ProfileError, match="harness must be one of"):
        find_profile("gemini", [folder])
    write(folder, "unknown", 'harness = "claude"\ncolour = "red"\n')
    with pytest.raises(ProfileError, match="unknown key 'colour'"):
        find_profile("unknown", [folder])
    write(folder, "old", 'harness = "claude"\nengine = "claude"\n')
    with pytest.raises(ProfileError, match="'engine' was renamed 'harness'"):
        find_profile("old", [folder])
    path = write(folder, "wrong", 'harness = "codex"\npermission_mode = "plan"\n')
    with pytest.raises(ProfileError, match="codex cannot honour it") as refused:
        find_profile("wrong", [folder])
    assert str(path) in str(refused.value)


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_passing_a_harness_to_find_profile_is_refused_naming_the_replacement(
        tmp_path, machine, harness):
    replacement = re.escape(f"find_profile('{harness}-read')")
    calls = [
        lambda: find_profile("read", harness),
        lambda: find_profile("read", harness, [tmp_path]),
        lambda: find_profile("read", harness, [tmp_path], environ={}),
        lambda: find_profile("read", harness=harness),
        lambda: find_profile("read", [tmp_path], harness=harness),
    ]
    for call in calls:
        with pytest.raises(TypeError, match=re.escape("takes no harness since 0.5.0")) as refused:
            call()
        assert re.search(replacement, str(refused.value))
    with pytest.raises(TypeError, match="takes no harness") as refused:
        find_profile("mine", harness, [tmp_path])
    assert "find_profile(name)" in str(refused.value)


def test_a_single_folder_string_is_refused_rather_than_searched_per_character(tmp_path, machine):
    for call in (lambda: find_profile("claude-read", str(tmp_path)),
                 lambda: find_profile_file("claude-read", str(tmp_path)),
                 lambda: list_profiles(str(tmp_path)),
                 lambda: find_profile("claude-read", tmp_path)):
        with pytest.raises(TypeError, match=re.escape("pass [folder]")):
            call()


def test_find_profile_takes_a_name_and_folders_only():
    import inspect

    assert list(inspect.signature(find_profile).parameters) == ["name", "folders", "environ"]
    assert list(inspect.signature(find_profile_file("claude-read").profile).parameters) == []


@pytest.mark.parametrize("name", ["../read", "a/b", ".hidden", "", "x" * 65, "a..b", "read.toml/",
                                  "~root", "a b"])
def test_unsafe_names_are_refused(tmp_path, machine, name):
    with pytest.raises(ProfileError, match="is not allowed"):
        find_profile(name, [tmp_path])


def test_an_unknown_name_is_not_found(machine):
    with pytest.raises(ProfileNotFound, match="no profile named 'nope'") as refused:
        find_profile("nope")
    assert "split" not in str(refused.value)


@pytest.mark.parametrize("name", ["read", "act", "read-sandboxed"])
def test_the_split_shipped_names_are_refused_naming_the_harness_prefixed_ones(
        tmp_path, machine, name, capsys):
    assert not shipped_folder().joinpath(f"{name}.toml").is_file()
    for call in (lambda: find_profile(name), lambda: find_profile_file(name, [tmp_path])):
        with pytest.raises(ProfileNotFound) as refused:
            call()
        message = str(refused.value)
        assert f"no profile named {name!r}" in message
        assert f"'claude-{name}'" in message and f"'codex-{name}'" in message
        assert "0.5.0" in message
    assert main(["profiles", "show", name]) == 2
    assert f"'claude-{name}'" in capsys.readouterr().err
    # A caller's own file of that name is found as any other.
    write(tmp_path, name, flat("codex", "mine"))
    assert find_profile(name, [tmp_path]).model == "mine"


def test_the_listing_shows_every_visible_profile_its_harness_and_what_it_shadows(
        tmp_path, machine):
    folder = tmp_path / "mine"
    write(folder, "claude-read", flat("codex", "mine"))
    write(folder, "solo", flat("claude", "x"))
    write(machine, "claude-read", flat("claude", "machine"))
    write(machine, "broken", "[claude\n")
    write(machine, "old", "[claude]\n")
    (folder / "notes.txt").write_text("not a profile")
    (folder / ".hidden.toml").write_text('harness = "claude"\n')
    listing = {entry.name: entry for entry in list_profiles([folder])}
    assert sorted(listing) == sorted([*SHIPPED, "broken", "old", "solo"])
    read = listing["claude-read"]
    assert (read.source, read.path, read.harness) == ("folder", str(folder / "claude-read.toml"),
                                                    "codex")
    assert read.shadows == (str(machine / "claude-read.toml"),
                            str(shipped_folder().joinpath("claude-read.toml")))
    assert listing["solo"].harness == "claude" and listing["solo"].shadows == ()
    for name in SHIPPED:
        if name != "claude-read":
            assert listing[name].source == "shipped"
            assert listing[name].harness == name.split("-")[0]
    assert listing["broken"].harness is None and "not valid TOML" in listing["broken"].error
    assert listing["old"].harness is None and FLAT_FORM in listing["old"].error
    assert "error" not in read.to_dict() and read.to_dict()["shadows"] == list(read.shadows)
    assert read.to_dict()["harness"] == "codex" and "harnesses" not in read.to_dict()


def test_the_old_harnesses_attributes_are_refused_naming_harness(tmp_path, machine):
    file = find_profile_file("codex-act")
    assert file.harness == "codex"
    with pytest.raises(AttributeError, match=re.escape(
            "ProfileFile.harnesses was replaced by ProfileFile.harness in 0.5.0")):
        file.harnesses()
    with pytest.raises(AttributeError, match=re.escape(
            "ProfileFile.tables was replaced by ProfileFile.knobs in 0.5.0")):
        file.tables()
    entry = list_profiles()[0]
    with pytest.raises(AttributeError, match=re.escape(
            "ProfileListing.harnesses was replaced by ProfileListing.harness in 0.5.0")):
        _ = entry.harnesses
    with pytest.raises(AttributeError, match="has no attribute 'nothing'"):
        _ = file.nothing


def test_only_the_six_harness_prefixed_profiles_ship():
    shipped = sorted(entry.name[:-5] for entry in shipped_folder().iterdir()
                     if entry.name.endswith(".toml"))
    assert shipped == sorted(SHIPPED)


@pytest.mark.parametrize("name", SHIPPED)
def test_each_shipped_profile_loads_on_its_harness(machine, name):
    harness = name.split("-")[0]
    file = find_profile_file(name)
    assert file.source == "shipped" and file.harness == harness
    profile = find_profile(name)
    assert isinstance(profile, Profile) and profile.harness == harness
    assert profile.model == {"claude": "opus", "codex": "gpt-6.1-sol"}[harness]
    assert profile.effort == "medium" and profile.timeout_seconds == 3600


def test_shipped_read_is_held_by_instruction_only(machine):
    claude, codex = find_profile("claude-read"), find_profile("codex-read")
    assert claude.permission_mode == "bypassPermissions" and claude.settings is None
    assert claude.setting_sources == ("project", "local") and claude.tools is None
    # No settings at all, so the target's hooks run.
    assert codex.codex_config == {"sandbox_mode": "danger-full-access"}
    for profile in (claude, codex):
        assert profile.append_system_prompt == READ_ONLY
        assert profile.env_set == {"CAPABILITIES_READ_ONLY": "1"}


def test_shipped_act_has_full_access(machine):
    claude, codex = find_profile("claude-act"), find_profile("codex-act")
    assert claude.permission_mode == "bypassPermissions" and claude.setting_sources is None
    assert codex.approval_policy == "never"
    assert codex.codex_config == {"sandbox_mode": "danger-full-access"}
    assert claude.env_set == {} and "full write access" in claude.append_system_prompt


def test_shipped_read_sandboxed_is_enforced_by_the_os(machine):
    claude = find_profile("claude-read-sandboxed")
    codex = find_profile("codex-read-sandboxed")
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


def test_the_cli_lists_and_shows_with_the_harness(tmp_path, machine, capsys):
    folder = tmp_path / "mine"
    path = write(folder, "claude-read", flat("claude", "mine"))
    write(folder, "old", "[codex]\n")
    assert main(["profiles", "--folder", str(folder)]) == 0
    listing = {e["name"]: e for e in json.loads(capsys.readouterr().out)}
    read = listing["claude-read"]
    assert read["source"] == "folder" and read["path"] == str(path)
    assert read["harness"] == "claude" and len(read["shadows"]) == 1
    assert listing["codex-act"]["source"] == "shipped"
    assert listing["codex-act"]["harness"] == "codex"
    assert listing["old"]["harness"] is None and FLAT_FORM in listing["old"]["error"]
    assert main(["profiles", "show", "claude-read", "--folder", str(folder)]) == 0
    assert capsys.readouterr().out == (f"# folder: {path}\n# harness: claude\n"
                                       + flat("claude", "mine"))
    assert main(["profiles", "show", "codex-read-sandboxed"]) == 0
    shown = capsys.readouterr().out
    assert shown.startswith("# shipped: ") and "\n# harness: codex\n" in shown
    assert ":read-only" in shown
    assert main(["profiles", "show", "old", "--folder", str(folder)]) == 0
    assert FLAT_FORM in capsys.readouterr().out.splitlines()[1]
    assert main(["profiles", "show", "../x"]) == 2
    assert "is not allowed" in capsys.readouterr().err

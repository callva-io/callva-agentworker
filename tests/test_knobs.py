import dataclasses
import re

import pytest

from callva.harness_runner import PROFILE_SCHEMA, Profile
from callva.harness_runner.__main__ import main
from callva.harness_runner.knobs import describe, docstrings

FIELDS = [f.name for f in dataclasses.fields(Profile)]


def blocks(text: str) -> dict[str, list[str]]:
    """The knobs output as {knob: its indented lines}."""
    found: dict[str, list[str]] = {}
    for block in text.strip().split("\n\n"):
        name, *lines = block.splitlines()
        found[name] = [line.strip() for line in lines]
    return found


def test_every_profile_field_is_described_from_its_homes(capsys):
    assert main(["knobs"]) == 0
    shown = blocks(capsys.readouterr().out)
    assert list(shown) == FIELDS
    docs = docstrings()
    assert set(docs) == set(FIELDS) == set(PROFILE_SCHEMA["properties"])
    for name, lines in shown.items():
        labels = [line.split(":", 1)[0] for line in lines]
        assert labels == ["type", "allowed", "default", "claude", "codex"], name
    assert shown["harness"][2] == "default: required"
    assert shown["timeout_seconds"][2] == "default: 600.0"
    assert shown["approval_policy"][1] == 'allowed: "never", "auto_review"'
    assert shown["setting_sources"][0] == "type: array of string or null"
    assert "Refused" in shown["codex_config"][3] and "Refused" in shown["budget_usd"][4]


def test_the_meaning_on_each_harness_is_its_part_of_the_docstring():
    [effort] = [k for k in describe() if k["name"] == "effort"]
    doc = docstrings()["effort"]
    claude_part = re.search(r"Claude: (.*?) Codex:", doc).group(1)
    assert effort["meaning"]["claude"] == claude_part
    assert effort["meaning"]["codex"].startswith("The turn's reasoning effort")


def test_one_harness_shows_only_its_meaning(capsys):
    assert main(["knobs", "--harness", "codex"]) == 0
    shown = blocks(capsys.readouterr().out)
    assert list(shown) == FIELDS
    assert all(not line.startswith("claude:") for lines in shown.values() for line in lines)
    assert any("app-server's thread override" in line for line in shown["bypass_hook_trust"])


def test_a_valid_profile_file_checks_ok_with_its_harness(tmp_path, capsys):
    path = tmp_path / "mine.toml"
    path.write_text('harness = "codex"\nmodel = "m"\nbypass_hook_trust = true\n'
                    'codex_config = { sandbox_mode = "read-only" }\n')
    assert main(["profiles", "check", str(path)]) == 0
    assert capsys.readouterr().out == f"ok: {path}: harness codex\n"


@pytest.mark.parametrize("text,knob", [
    ('harness = "claude"\nmodle = "opus"\n', "unknown key 'modle'"),
    ('harness = "codex"\npermission_mode = "plan"\n', "profile.permission_mode"),
    ('harness = "claude"\nbypass_hook_trust = true\n', "profile.bypass_hook_trust"),
])
def test_a_refused_profile_file_names_the_knob_and_fails(tmp_path, capsys, text, knob):
    path = tmp_path / "bad.toml"
    path.write_text(text)
    assert main(["profiles", "check", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and knob in captured.err and str(path) in captured.err


def test_a_missing_profile_file_fails(tmp_path, capsys):
    assert main(["profiles", "check", str(tmp_path / "none.toml")]) == 2
    assert "none.toml" in capsys.readouterr().err

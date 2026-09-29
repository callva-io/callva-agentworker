"""0.3.0 renamed engine to harness. There are no aliases: each old name is refused
with a message that names its replacement."""

import re

import pytest

import callva.harness_runner as harness_runner
from callva.harness_runner import FailureKind, Probe, Profile, ProfileError, Result


def test_the_profile_refuses_engine_in_configuration_and_in_code():
    with pytest.raises(ProfileError, match=re.escape("'engine' was renamed 'harness' in 0.3.0")):
        Profile.from_dict({"engine": "claude"})
    with pytest.raises(ProfileError, match=re.escape("'engine' was renamed 'harness' in 0.3.0")):
        Profile(engine="claude")
    assert Profile(harness="codex").harness == "codex"


def test_the_profile_refuses_the_0_1_keys_in_code_too():
    with pytest.raises(ProfileError, match=re.escape("'fence' was removed in 0.2.0")):
        Profile(harness="claude", fence="read")


@pytest.mark.parametrize("old,new", [("engine", "harness"), ("engine_version", "harness_version")])
def test_the_result_refuses_its_old_fields(old, new):
    result = Result(ok=True, harness="claude", harness_version="2.1.280")
    refused = f"Result.{old} was renamed Result.{new} in 0.3.0"
    with pytest.raises(AttributeError, match=re.escape(refused)):
        getattr(result, old)
    assert "engine" not in result.to_dict() and result.to_dict()["harness"] == "claude"


def test_the_failure_kind_refuses_its_old_name_and_value():
    assert FailureKind.INCOMPATIBLE_HARNESS == "incompatible_harness"
    refused = "INCOMPATIBLE_ENGINE was renamed FailureKind.INCOMPATIBLE_HARNESS"
    with pytest.raises(AttributeError, match=re.escape(refused)):
        _ = FailureKind.INCOMPATIBLE_ENGINE
    with pytest.raises(ValueError, match="incompatible_engine was renamed incompatible_harness"):
        FailureKind("incompatible_engine")


def test_the_package_and_probe_refuse_their_old_names():
    assert harness_runner.HARNESSES == ("claude", "codex")
    refused = "ENGINES was renamed callva.harness_runner.HARNESSES"
    with pytest.raises(ImportError, match=re.escape(refused)):
        _ = harness_runner.ENGINES
    with pytest.raises(AttributeError, match=re.escape("Probe.engine was renamed Probe.harness")):
        _ = Probe("claude", False).engine
    with pytest.raises(AttributeError, match="has no attribute 'nothing'"):
        _ = harness_runner.nothing


@pytest.mark.parametrize("module", ["callva.harness_runner", "callva.harness_runner.profile"])
def test_a_from_import_of_an_old_name_keeps_the_rename_message(module):
    refused = f"{module}.ENGINES was renamed {module}.HARNESSES in 0.3.0"
    with pytest.raises(ImportError, match=re.escape(refused)):
        exec(f"from {module} import ENGINES")
    with pytest.raises(ImportError, match="cannot import name 'nothing'"):
        exec(f"from {module} import nothing")


def test_the_profile_refuses_its_old_field():
    profile = Profile.from_dict({"harness": "claude"})
    refused = "Profile.engine was renamed Profile.harness in 0.3.0"
    with pytest.raises(AttributeError, match=re.escape(refused)):
        _ = profile.engine
    assert not hasattr(profile, "nothing")

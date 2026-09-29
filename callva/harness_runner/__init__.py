"""One headless turn of a coding agent, run through the vendor's own SDK.

    from callva.harness_runner import Profile, run

    result = run(prompt, Profile.from_dict(config), cwd=".")
    if result.ok:
        print(result.answer)
    else:
        print(result.failure.kind, result.failure.message)

`DESIGN.md` in the repository is the contract.
"""

from .binaries import Probe, find_binary, probe
from .discovery import (
    ProfileFile,
    ProfileListing,
    ProfileNotFound,
    find_profile,
    find_profile_file,
    list_profiles,
    machine_folder,
)
from .guard import TESTED_VERSIONS
from .profile import (
    HARNESSES,
    PROFILE_SCHEMA,
    SESSION_MARKERS,
    Profile,
    ProfileError,
    Session,
    load_profile_schema,
    validate_profile,
)
from .renamed import refuse_module_attribute
from .result import Failure, FailureKind, Result, Tokens
from .run import run
from .version import __version__


def __getattr__(name: str):
    raise refuse_module_attribute(__name__, name)


__all__ = [
    "HARNESSES",
    "PROFILE_SCHEMA",
    "SESSION_MARKERS",
    "TESTED_VERSIONS",
    "Failure",
    "FailureKind",
    "Probe",
    "Profile",
    "ProfileError",
    "ProfileFile",
    "ProfileListing",
    "ProfileNotFound",
    "Result",
    "Session",
    "Tokens",
    "__version__",
    "find_binary",
    "find_profile",
    "find_profile_file",
    "list_profiles",
    "load_profile_schema",
    "machine_folder",
    "probe",
    "run",
    "validate_profile",
]

"""One headless turn of a coding agent, run through the vendor's own SDK.

    from callva.agentworker import Profile, run

    result = run(prompt, Profile.from_dict(config), cwd=".")
    if result.ok:
        print(result.answer)
    else:
        print(result.failure.kind, result.failure.message)

`DESIGN.md` in the repository is the contract.
"""

from .binaries import Probe, find_binary, probe
from .guard import TESTED_VERSIONS
from .profile import (
    ENGINES,
    PROFILE_SCHEMA,
    SESSION_MARKERS,
    Profile,
    ProfileError,
    Session,
    load_profile_schema,
    validate_profile,
)
from .result import Failure, FailureKind, Result, Tokens
from .run import run
from .version import __version__

__all__ = [
    "ENGINES",
    "PROFILE_SCHEMA",
    "SESSION_MARKERS",
    "TESTED_VERSIONS",
    "Failure",
    "FailureKind",
    "Probe",
    "Profile",
    "ProfileError",
    "Result",
    "Session",
    "Tokens",
    "__version__",
    "find_binary",
    "load_profile_schema",
    "probe",
    "run",
    "validate_profile",
]

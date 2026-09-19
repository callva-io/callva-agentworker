"""One headless turn of a coding agent: launch, run, read, classify.

    from callva.agentworker import Profile, Session, run

    result = run("Summarise README.md in one line.",
                 Profile(engine="claude", fence="read", timeout_seconds=120),
                 cwd=".")
    if result.ok:
        print(result.answer)
    else:
        print(result.failure.kind, result.failure.message)

`DESIGN.md` in the repository is the contract.
"""

from .binaries import Probe, find_binary, probe
from .profile import (
    DEFAULT_DENY,
    ENGINES,
    FENCES,
    PROFILE_SCHEMA,
    EnvPolicy,
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
    "DEFAULT_DENY",
    "ENGINES",
    "FENCES",
    "PROFILE_SCHEMA",
    "EnvPolicy",
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

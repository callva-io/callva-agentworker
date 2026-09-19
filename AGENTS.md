# callva-agentworker

One headless turn of a coding agent, as a Python library with no dependencies. `DESIGN.md` is the contract: read it before changing anything, and change it in the same commit as the behaviour it describes.

## Working here

- The public surface is what `callva/agentworker/__init__.py` exports. Everything else is internal and may move.
- Every engine flag lives in exactly one builder: `claude.py` or `codex.py`. A consumer that needs a flag the profile does not model passes it through `extra_args`; do not add profile fields for one caller.
- The result shape never loses a field; new fields are added with `None` as the value for engines that cannot report them.
- Failures carry the engine's own sentence in `message`. Classification is a reading of that sentence, never a replacement for it.
- Tests run on fake engines under `tests/fakes/`. A change to a command line or a parser gets a test on the fake; a live run against a real engine is a manual smoke, recorded in the pull request, not a test.
- Versioning: `callva/agentworker/version.py` is the one home. In 0.x the minor is the breaking position: a changed field meaning, a removed flag, a different default fence is a minor; an added field or an added engine option is a patch.

## Release

Bump `version.py`, commit with the version as the title, tag `vX.Y.Z`, publish a GitHub release. The publish workflow builds and uploads through PyPI trusted publishing; nothing is stored.

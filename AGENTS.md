# callva-agentworker

One headless turn of a coding agent, run through the vendors' SDKs. `DESIGN.md` is the contract: read it before changing anything, and change it in the same commit as the behaviour it describes.

## Working here

- The public surface is what `callva/agentworker/__init__.py` exports. Everything else is internal and may move.
- Every knob maps to its engine in exactly one place: `claude.py` or `codex.py`. A consumer that needs a flag no knob names passes it through `claude_extra_args` or `codex_extra_args`; do not add knobs for one caller. A knob an engine cannot honour is refused in `profile.py`, never ignored.
- The result shape never loses a field; new fields are added with `None` as the value for engines that cannot report them.
- Failures carry the engine's own sentence in `message`. Classification is a reading of that sentence, never a replacement for it.
- Tests run on fake engines under `tests/fakes/` that speak the SDKs' own protocols (claude's stream-json, codex's app-server JSON-RPC). A change to a knob's mapping or to a reader gets a test on the fake; a live run against a real engine is a manual smoke, recorded in the pull request, not a test.
- Versioning: `callva/agentworker/version.py` is the one home. In 0.x the minor is the breaking position: a changed field meaning, a removed knob or a changed default is a minor; an added field, an added knob whose default leaves the engine alone, or a widened tested range is a patch. The tested CLI range lives in `guard.py`; widen it only after a run against that CLI.

## Release

Bump `version.py`, commit with the version as the title, tag `vX.Y.Z`, publish a GitHub release. The publish workflow builds and uploads through PyPI trusted publishing; nothing is stored.

# callva-harness-runner

One run of an agent harness from a profile, through the vendors' SDKs. `DESIGN.md` is the contract: read it before changing anything, and change it in the same commit as the behaviour it describes.

## Working here

- The public surface is what `callva/harness_runner/__init__.py` exports. Everything else is internal and may move.
- Every knob maps to its harness in exactly one place: `claude.py` or `codex.py`. A consumer that needs a flag no knob names passes it through `claude_extra_args` or `codex_extra_args`; do not add knobs for one caller. A knob a harness cannot honour is refused in `profile.py`, never ignored.
- The result shape never loses a field; new fields are added with `None` as the value for harnesses that cannot report them.
- Failures carry the harness's own sentence in `message`. Classification is a reading of that sentence, never a replacement for it.
- Tests run on fake harnesses under `tests/fakes/` that speak the SDKs' own protocols (claude's stream-json, codex's app-server JSON-RPC). A change to a knob's mapping or to a reader gets a test on the fake; a live run against a real harness is a manual smoke, recorded in the pull request, not a test.
- The shipped profiles live in `callva/harness_runner/profiles/`. Changing one changes what a run does: prove it with a live run on both harnesses, and for `read-sandboxed` show a write in the target blocked while the network and `~/.cache` work.
- Versioning: `callva/harness_runner/version.py` is the one home of the number, and DESIGN section 12 holds the rule. The tested CLI range lives in `guard.py`; widen it only after a run against that CLI.

## Release

Bump `version.py`, commit with the version as the title, tag `vX.Y.Z`, publish a GitHub release. The publish workflow builds and uploads through PyPI trusted publishing; nothing is stored.

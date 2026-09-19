# callva-agentworker

One headless turn of a coding agent, as a Python library with no dependencies. It launches Claude Code or Codex with the flags that make a fence real, keeps the process under a deadline, reads the engine's own report tolerantly, and hands back one result with the failure named. Nothing else: no queue, no schedule, no ledger.

`DESIGN.md` is the contract.

## Install

```
pip install callva-agentworker
```

In a PEP 723 script, pin the exact version so nothing outside the script's own release changes what it runs:

```python
# /// script
# dependencies = ["callva-agentworker==0.1.0"]
# ///
```

## Use

```python
from callva.agentworker import Profile, Session, run

result = run(
    "Summarise README.md in one line.",
    Profile(engine="claude", fence="read", timeout_seconds=120),
    cwd="/path/to/project",
)
if result.ok:
    print(result.answer, result.cost_usd, result.session_id)
else:
    print(result.failure.kind, result.failure.message)
```

`run()` never raises for anything the engine did. Every ending is a `Result`; `result.failure.kind` says what kind, and `result.failure.message` carries the engine's own sentence.

### Profile

How the turn is run. Keep profiles in your own configuration and validate them with the schema the package ships:

```python
from callva.agentworker import Profile, PROFILE_SCHEMA

profile = Profile.from_dict({
    "engine": "codex",
    "fence": "act",
    "model": "gpt-5-codex",
    "effort": "high",
    "timeout_seconds": 3600,
    "env": {"deny": ["SECRET_*"], "set": {"TASKS_EXECUTION": "exec-42"}},
})
```

| Field | Meaning |
|---|---|
| `engine` | `claude` or `codex` |
| `fence` | `read`, `write` or `act`; enforced by the engine, never by the prompt, and independent of the machine's own settings files |
| `model`, `effort`, `service_tier` | passed through; `None` leaves the engine's default |
| `timeout_seconds` | the deadline; the whole process tree is killed when it passes |
| `budget_usd` | claude only |
| `allow_tools` | extra tool patterns a fenced turn may use, such as `Bash(tasks:*)` |
| `add_dirs` | directories beyond the working directory a fenced turn's file tools may reach |
| `env` | which inherited variables reach the engine: `allow`, `deny`, `set` |
| `extra_args` | appended verbatim; the escape hatch |

### Session

`Session.fresh()` starts a conversation; on claude the id is chosen before launch so a killed turn is still addressable, on codex it is learned from the stream. `Session.resume(id)` continues one. `Session.pinned(id)` chooses the id and is claude-only.

### Result

`ok`, `answer`, `structured`, `session_id`, `model`, `cost_usd`, `duration_ms`, `num_turns`, `tokens`, `permission_denials`, `failure`, `exit_code`, `stderr_tail`, `command`, `raw`. Fields an engine cannot report are `None`.

### Failure kinds

`quota`, `model_refused`, `not_authenticated`, `timeout`, `cancelled`, `binary_missing`, `max_turns`, `budget`, `invalid_output`, `error`, `crash`. An HTTP status the engine reports is read before its sentence, and a spent quota before a refused model, because a subscription spent on one model says both and only one of them is a pause. `failure.retryable` is true for the kinds where running the same turn again later can succeed.

### Progress and cancel

Pass `on_event` to receive every JSON event the engine streams while the turn runs, and render it yourself. Pass a `threading.Event` as `cancel` to end a turn early; the whole tree is killed.

### Structured answers

Pass `schema` as a JSON-schema dict. The engine's native flag is used; if the engine returned no structured field the answer text is parsed, and if that fails the turn is an `invalid_output` failure with the text kept.

## Versioning

SemVer with the 0.x rule: the minor is the breaking position. A changed field meaning, a removed flag or a changed default is a minor; an added result field, an added profile field with a `None` default, or a newly supported engine option is a patch.

## License

Apache-2.0.

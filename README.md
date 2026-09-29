# callva-agentworker

One headless turn of a coding agent, as a Python library. It runs Claude Code through Anthropic's `claude-agent-sdk` or Codex through OpenAI's `openai-codex`, always against the CLI installed on the machine, configured only by a profile of explicit knobs. It keeps the turn under a deadline that kills everything the engine started, reads what the engine reported, and hands back one result with the failure named. It ships no presets and no fences: what a turn may do is whatever its profile says, and nothing else.

`DESIGN.md` is the contract.

## Install

```
pip install callva-agentworker
```

It depends on `claude-agent-sdk==0.2.161` and `openai-codex==0.159.0`, pinned exactly; together they add about 0.5 GB, most of it the CLIs both SDKs bundle. The bundled CLIs are never run: the library always runs the CLI installed on the machine.

In a PEP 723 script, pin the exact version so nothing outside the script's own release changes what it runs:

```python
# /// script
# dependencies = ["callva-agentworker==0.2.0"]
# ///
```

## Use

```python
from callva.agentworker import Profile, Session, run

profile = Profile.from_dict(config["profile"])   # your configuration, your knobs
result = run("Summarise README.md in one line.", profile, cwd="/path/to/project")
if result.ok:
    print(result.answer, result.cost_usd, result.session_id)
else:
    print(result.failure.kind, result.failure.message)
```

`run()` never raises for anything the engine did. Every ending is a `Result`; `result.failure.kind` says what kind, and `result.failure.message` carries the engine's own sentence. It raises `ValueError` only for a request it cannot express, such as a pinned session on codex.

`run(prompt, profile, cwd, *, session=None, environ=None, extra_env=None, on_event=None, cancel=None, stderr_tail=40)`:

- `session`: `Session.fresh()` (the default), `Session.pinned(id)` or `Session.resume(id)`, below.
- `environ`: the environment the engine starts from; this process's by default. A variable absent from it is absent in the engine, even though both SDKs inherit this process's environment.
- `extra_env`: variables set on top of `environ` and the profile's `env_set`.
- `on_event`: called with one dict per engine event while the turn runs. On claude it is the SDK's message: a system message is the engine's own event (`subtype` `init` carries `apiKeySource`, `model` and `claude_code_version`), any other message is its fields plus `type`, the SDK class name. On codex it is `{"method", "params"}`, one app-server notification.
- `cancel`: a `threading.Event`; setting it ends the turn and kills its processes.

## Profile

A profile is a flat set of explicit knobs. There is no inheritance, no preset and no fence. A knob left at its default leaves the engine's own default in place. A knob one engine cannot honour is refused for that engine with a `ProfileError` when the profile is built, never ignored while it runs. Each knob's docstring on `Profile` says what it does on each engine; `PROFILE_SCHEMA` (shipped as `profile.schema.json`) validates a profile kept in configuration, and `Profile.from_dict` refuses unknown keys.

| Knob | claude | codex |
|---|---|---|
| `engine` | `claude` | `codex` |
| `cli_path` | the CLI the SDK launches; `None` finds the installed `claude` | the binary whose `app-server` the SDK talks to; `None` finds the installed `codex` |
| `model` | `--model` | the thread's model |
| `effort` | `--effort` | the turn's reasoning effort |
| `timeout_seconds` | the deadline; default 600 | the same |
| `budget_usd` | `--max-budget-usd` | refused: codex reports no cost |
| `tools` | `--tools`, the built-in tools that exist; `[]` removes them all | refused |
| `allowed_tools` | `--allowedTools`, patterns that run without a prompt | refused |
| `disallowed_tools` | `--disallowedTools` | refused |
| `permission_mode` | `--permission-mode` | refused: use `approval_policy` and `codex_config` |
| `setting_sources` | `--setting-sources`; `["project", "local"]` loads the target's CLAUDE.md, rules and hooks without the user's | refused |
| `settings` | `--settings`, an object or path layered above the settings files: sandbox, permissions | refused: use `codex_config` |
| `mcp_config` | `--mcp-config`, `{"mcpServers": {...}}` or a path | refused: `mcp_servers` in `codex_config` |
| `strict_mcp` | `--strict-mcp-config` | refused |
| `add_dirs` | `--add-dir` per entry | refused: give the directory access in `codex_config` permissions |
| `append_system_prompt` | appended to the Claude Code system prompt | the thread's developer instructions |
| `output_schema` | `--json-schema` | the turn's output schema |
| `name` | `--name` | the thread's name |
| `env_set` | set in the engine's environment | the same |
| `env_remove` | names or globs removed from what the engine inherits | the same |
| `strip_session_markers` | also remove `SESSION_MARKERS`; default true | the same |
| `codex_config` | refused: use `settings` | the thread's config, keyed as in `config.toml`: permission profiles, `sandbox_mode`, network, `mcp_servers` |
| `approval_policy` | refused: use `permission_mode` | `never` (escalations refused) or `auto_review` (codex's reviewer decides); `None` is the SDK default, `auto_review` |
| `service_tier` | refused | the thread's service tier |
| `bypass_hook_trust` | refused: claude has no hook trust | refused when true: the app-server has no hook-trust bypass, so hooks run only when the machine trusts them |
| `claude_extra_args` | extra CLI flags, `{"flag": "value"}` or `{"flag": None}` | refused |
| `codex_extra_args` | refused | arguments before `app-server`, such as `["-c", "key=value"]` |

Claude always runs on the `claude_code` system-prompt preset, so a turn has the same prompt `claude -p` has; the library never replaces either engine's system prompt, and `append_system_prompt` only adds to it.

### Environment

Both SDKs only add to the environment they inherit. To remove a variable for real, the library puts a small launcher of its own in front of the CLI: the SDK starts the launcher, the launcher removes what the profile removes and becomes the CLI. The launcher learns names, never values. `SESSION_MARKERS` are the variables a running Claude Code session leaves in its children (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_EFFORT`, `AI_AGENT` and the rest); a child engine that inherits them believes it runs inside that session, so they are removed unless `strip_session_markers` is false. On claude the values the SDK itself sets for the CLI, such as its entrypoint, stay.

### Deadline and cancel

The launcher makes the engine a session leader. When the deadline passes, or `cancel` is set, no further engine start is allowed, and the engine, every process it started, and everything those left behind in their process group or session are sent SIGTERM and then SIGKILL, grandchildren included. A caller that is itself killed cannot do this, and the engine's tree then outlives it.

## Harness guard

`TESTED_VERSIONS` holds, per engine, the range of CLI versions this release was tested with: claude 2.1.280 to 2.1.284, codex 0.159.0. Before a turn the library reads the installed CLI's `--version`:

- older than the range: the turn is refused with failure kind `incompatible_engine`, and the message names the installed version and the tested one;
- newer than the range: the turn runs, and `result.warnings` names both versions;
- no CLI: `binary_missing`, as before.

## Session

`Session.fresh()` starts a conversation; on claude the id is chosen before launch so a killed turn is still addressable, on codex it is the thread id the app-server gives. `Session.resume(id)` continues one on either engine. `Session.pinned(id)` chooses the id and is claude-only.

## Result

| Field | Meaning |
|---|---|
| `ok` | the engine confirmed a completed turn with an answer |
| `engine` | `claude` or `codex` |
| `answer` | the final text |
| `structured` | the parsed answer when `output_schema` was given |
| `session_id` | claude session id or codex thread id, set whenever known, including after a kill |
| `model` | the model that ran when claude reports it, else the requested one |
| `cost_usd` | claude's own estimate; `None` on codex |
| `duration_ms`, `num_turns` | as reported; `num_turns` is `None` on codex |
| `tokens` | `input`, `output`, `cache_read`, `cache_creation` for this turn |
| `permission_denials` | claude's list; empty on codex |
| `failure` | `None` when `ok`; else `kind` and the engine's own `message` |
| `exit_code` | the exit code the claude SDK reported for a failed process, else `None` |
| `stderr_tail` | the engine's last stderr lines, for a person |
| `command` | the CLI command line the launcher started |
| `raw` | claude's result message, or codex's `{"turn", "items", "errors"}` |
| `engine_version` | the installed CLI version the guard read |
| `warnings` | the guard's warning when the CLI is newer than tested |

### Failure kinds

`quota`, `model_refused`, `not_authenticated`, `timeout`, `cancelled`, `binary_missing`, `max_turns`, `budget`, `invalid_output`, `error`, `crash`, `incompatible_engine`. The engine's own verdict is read first (claude's result subtype, codex's `codexErrorInfo`), then an HTTP status it reports, then its sentence: a spent quota before a refused model, because a subscription spent on one model says both and only one of them is a pause. A claude turn that times out while the engine is retrying a 401 or a 429 is `not_authenticated` or `quota`. `failure.retryable` is true for the kinds where running the same turn again later can succeed.

## Changelog

### 0.2.0

The engines now run through the vendors' SDKs, and the profile is explicit knobs. What a 0.1.x consumer must change:

- `fence` is gone, and so is its default. A 0.1.x profile that named no fence ran fenced to `read`; the same profile now runs with the engine's own defaults. State what the turn may do with `tools`, `allowed_tools`, `disallowed_tools`, `permission_mode`, `setting_sources`, `settings`, `mcp_config` and `strict_mcp` on claude, and `codex_config` and `approval_policy` on codex. `Profile.from_dict` refuses a `fence` key with a message naming these knobs, and `Profile.fence` no longer exists.
- `allow_tools` becomes `tools` plus `allowed_tools`. `env` (`allow`, `deny`, `set`) becomes `env_set`, `env_remove` and `strip_session_markers`; there is no allow-list. `extra_args` becomes `claude_extra_args` (a mapping) or `codex_extra_args`. `EnvPolicy`, `DEFAULT_DENY` and `FENCES` are no longer exported.
- `run()` loses `schema` (now the profile's `output_schema`), `name` (now the profile's `name`) and `prompt_via` (the prompt always travels over the SDK's own channel).
- A knob the engine cannot honour is refused instead of ignored: `budget_usd` on codex, `service_tier` on claude.
- `on_event` receives SDK messages (claude) and app-server notifications (codex) instead of CLI JSON lines. `raw` changes shape the same way, `command` is the command line the launcher started, and `exit_code` is `None` unless the claude SDK reported one.
- A CLI older than the tested range is refused with the new kind `incompatible_engine`; `Result` gains `engine_version` and `warnings`.
- Two dependencies arrive, about 0.5 GB.

Unchanged: `Profile.from_dict`, `Session.fresh`, `Session.pinned`, `Session.resume`, `run(prompt, profile, cwd, session=, environ=, extra_env=, on_event=, cancel=)`, `FailureKind`, and every 0.1.x `Result` field.

## Versioning

SemVer with the 0.x rule: the minor is the breaking position. A changed field meaning, a removed knob or a changed default is a minor; an added result field, an added knob whose default leaves the engine alone, or a widened tested range is a patch.

## License

Apache-2.0.

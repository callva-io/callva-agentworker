# Design

`callva-harness-runner` runs one turn of an agent harness from a profile and hands back one result. It exists because the same fifty lines of launch-and-parse code had been written nine times across one owner's tools, each with a different bug, and a tenth was about to be written.

## 1. Scope

One turn: a prompt goes in, a harness runs to its end or its deadline, one `Result` comes out. The library runs the harness through its vendor's SDK against the CLI installed on the machine, configures it only from the profile's explicit knobs, keeps every process it starts under the deadline, reads the harness's report, and classifies a failure by what the harness said. That is the whole job.

### Non-goals

It does not schedule, queue, retry, or loop. It holds no ledger, no session store, no conversation memory. It renders no progress; it hands events to a callback and the caller renders. It does not know what a task, a message or a job is. It ships no presets and no fences: it never decides what a turn may do. Presets belong to consumers.

## 2. Names

The vocabulary: a harness is the vendor's agent runtime (Claude Code, the Codex CLI); a profile is one harness configuration; a run is one turn. The library holds no queue and no long-lived consumer of work; those belong to its callers.

The distribution is `callva-harness-runner` and the import path is `callva.harness_runner`: the distribution name is the import path with dashes, the same rule `callva-livekit` follows, and `callva` is a namespace package with no `__init__.py` so the two coexist in one environment. It was `callva-agentworker` (`callva.agentworker`) up to 0.2.0; the README maps each old name to its new one, and every old name is refused with a message naming the new one. The three nouns a caller uses are `Profile` (how to run), `Session` (which conversation), and `Result` (what came back). `run()` is the one verb. `probe()` answers whether a harness is present.

## 3. Harnesses

`claude` is Claude Code through `claude-agent-sdk`; `codex` is Codex through `openai-codex`, which drives `codex app-server`. Both are dependencies pinned exactly, because an SDK release changes the protocol it speaks and the flags it passes.

Both SDKs bundle a CLI, and the library never runs it: it always passes the installed CLI (`cli_path` on claude, the `app-server` launch on codex). The CLI is the profile's `cli_path`, or else the first `claude` or `codex` on the caller's `PATH`, then in the places a login shell would have added and a launchd job does not: `~/.local/bin`, fnm and nvm node directories, Homebrew. Codex is started at the file a symlinked install points to, because it finds its companion executables beside the path it was started from.

Claude always runs on the `claude_code` system-prompt preset. The SDK's own default is a minimal prompt that is not Claude Code's; the preset keeps the prompt a `claude -p` turn has. Neither harness's system prompt is ever replaced; `append_system_prompt` adds to claude's and is codex's developer instructions.

Codex's turn is read from the turn's notification stream, not from `thread.run()`, which raises on a failed turn and drops `codexErrorInfo`.

## 4. Profile

A `Profile` is a frozen, flat record of explicit knobs. There is no inheritance and no named fence. A knob at its default leaves the harness's own default in place. A knob one harness cannot honour is refused for that harness when the profile is built, with a `ProfileError` naming the knob; it is never ignored while the turn runs. Each knob's docstring on `Profile` is the home of what it does on each harness, and the README carries the same table for readers of the package page.

The knobs: `harness`, `cli_path`, `model`, `effort`, `timeout_seconds`, `budget_usd`; `tools`, `allowed_tools`, `disallowed_tools`, `permission_mode`, `setting_sources`; `settings`, `mcp_config`, `strict_mcp`; `add_dirs`, `append_system_prompt`, `output_schema`, `name`; `env_set`, `env_remove`, `strip_session_markers`; `codex_config`, `approval_policy`, `service_tier`, `bypass_hook_trust`; `claude_extra_args`, `codex_extra_args`.

`Profile.from_dict()` validates against `profile.schema.json`, which ships in the package so that every consumer's configuration file is checked by the same rule. Unknown keys are refused, and the 0.1.x keys (`fence`, `allow_tools`, `env`, `extra_args`) are refused with a message naming the knobs that replace them.

Hook trust on codex is a knob that is refused on both harnesses. Over `app-server` there is no way to run a hook the machine has not trusted: `bypass_hook_trust` is not a config key (`--strict-config` rejects it) and the CLI's `--dangerously-bypass-hook-trust`, accepted before `app-server`, does not make an untrusted hook run, although the same hook runs under `codex exec` with it. Hooks the machine trusts run.

### Environment

Both SDKs merge the profile's variables over the environment the Python process has, and neither can remove one. The library therefore puts a launcher of its own where the SDK expects the CLI: a two-line shell script that runs `_launcher.py` with `python -I -S`, which removes the variables the turn removes and `exec`s the real CLI. What reaches the launcher is a spec of names and paths; a variable's value only ever travels through the SDK's own env option.

The harness's environment is the caller's `environ` (this process's by default), with the profile's `env_remove` globs and, unless `strip_session_markers` is false, `SESSION_MARKERS` removed, and with `env_set` and the call's `extra_env` set on top. A variable in `env_set` is never removed, and a profile that both sets and removes one name is refused. On claude the variables the SDK itself sets for the CLI (its entrypoint, its version, its session-state flag, `PWD`) are the SDK's values and are not removed.

## 5. Session

`Session.fresh()` starts a new conversation. On claude the library generates the id before launch and pins it, so a turn that is killed is still addressable. On codex the id is the thread id the app-server gives, reported even when the turn is later killed. `Session.pinned(id)` lets the caller choose the id; it is claude-only and refused on codex. `Session.resume(id)` continues an existing conversation on either harness; on codex the thread is resumed with the profile's model, config, developer instructions, service tier and approval policy.

## 6. Harness guard

`TESTED_VERSIONS` declares, per harness, the inclusive range of CLI versions the release was tested with: the low end is the CLI installed where the release was tested, the high end is the CLI the pinned SDK bundles. Before every turn the installed CLI's `--version` is read (cached per binary file):

- below the range, or unreadable: the turn is refused with `incompatible_harness`, naming both versions;
- above the range: the turn runs and `Result.warnings` names both versions;
- no CLI: `binary_missing`, as it was.

## 7. Running

The turn runs on a thread of its own; the calling thread holds the deadline and the cancel. The launcher records the harness's pid and command line and makes the harness a session leader. When the deadline passes or the caller's `threading.Event` is set, the library first writes a stop file that the launcher checks before any later start, then finds the harness's tree three ways: by parentage from the harness, by the process groups of what it found, and by the sessions of what it found, the harness's own included. The harnesses give each tool command a process group of its own, and a command that backgrounds a child and exits leaves that child with its group and session but a new parent, so parentage alone would miss it. The tree gets SIGTERM, three seconds, then SIGKILL; the caller's own group and session are never touched. Then the SDK is closed.

A caller killed outright cannot do any of this, and the harness's tree outlives it.

## 8. Reading

Claude: the SDK's `ResultMessage` gives `result` as the answer (its `errors` when there is none), `structured_output`, `session_id`, `total_cost_usd`, `duration_ms`, `num_turns`, the four token counts from `usage`, the model that ran from `modelUsage`, `permission_denials`, and `subtype` with `is_error` as the verdict. The SDK raises after it hands over an error result; the result is the report and the raise is not. The last `api_retry` event is kept, because a turn that dies by the deadline while the harness retries a 401 or a 429 has already said why.

Codex: the turn's `item/completed` notifications give the answer (the last agent message), `thread/tokenUsage/updated` gives this turn's tokens (the thread's running total less what it held before the turn), and `turn/completed` gives the status, the duration and the error with its `codexErrorInfo`. Cost is `None`: codex reports none under ChatGPT authentication.

When `output_schema` is given and the harness returned no structured field, the answer text is parsed as JSON; if that fails, the turn is an `invalid_output` failure with the text kept.

## 9. Result

| Field | Meaning |
|---|---|
| `ok` | the harness confirmed a completed turn: claude `subtype == "success"` and `is_error` false; codex status `completed`, no error, and a non-empty answer. |
| `harness` | which harness ran. |
| `answer` | the final text, possibly empty on failure. |
| `structured` | the parsed structured answer, or `None`. |
| `session_id` | claude session id or codex thread id; set whenever it is known, including after a kill. |
| `model` | the model that actually ran when claude reports it, else the requested one, else `None`. |
| `cost_usd`, `duration_ms`, `num_turns`, `tokens` | as reported; `None` where the harness does not say. |
| `permission_denials` | claude's list, empty on codex. |
| `failure` | `None` when `ok`; otherwise a kind and the harness's own sentence. |
| `exit_code` | the exit code the claude SDK reported for a failed process, else `None`. |
| `stderr_tail` | the last lines of the harness's stderr, for a person. |
| `command` | the CLI command line the launcher started. |
| `raw` | claude's result message as a dict, or codex's `{"turn", "items", "errors"}`, for anything this table left out. |
| `harness_version` | the CLI version the guard read. |
| `warnings` | the guard's warning when the CLI is newer than tested. |

## 10. Failure kinds

`quota`: the subscription or rate limit is spent; the turn can be retried later without changing anything. `model_refused`: the harness will not run this model; retrying changes nothing. `not_authenticated`: no login or an invalid key. `timeout`: the deadline passed and the tree was killed. `cancelled`: the caller's event was set. `binary_missing`: no harness found. `max_turns`, `budget`: the harness ended the turn on its own limit. `invalid_output`: a schema was required and nothing parsed. `error`: the harness reported a failure this table does not name; the sentence is in `message`. `crash`: the harness ended without a report. `incompatible_harness`: the installed CLI is older than the tested range, or its version cannot be read.

Classification reads the harness's own verdict first (claude's `error_max_turns` and budget subtypes; codex's `codexErrorInfo`: `usageLimitExceeded` and `rateLimitExceeded` are `quota`, `unauthorized` is `not_authenticated`, `sessionBudgetExceeded` is `budget`), then an HTTP status the harness reports (claude's `api_error_status` or its last `api_retry` status, codex's `httpStatusCode`: 429 is `quota`, 401 is `not_authenticated`), then the sentence, in a fixed order: quota before model refusal, because a spent subscription on one model says both, and only one of them is a pause. Codex wraps a provider's HTTP error as JSON; the sentence inside it is what is read and kept.

## 11. Constraints worth knowing

The cost claude reports is its own estimate and includes subagents; a turn that dies reports no cost at all, so an accumulated total is a floor. Codex under ChatGPT authentication reports tokens but no cost. A profile with no knobs runs the harness exactly as the machine configures it: user settings, hooks and MCP servers included. Hooks on codex run only when the machine trusts them.

## 12. Versioning

SemVer with the 0.x rule: the minor is the breaking position. A changed field meaning, a removed knob or a changed default is a minor; an added result field, an added knob whose default leaves the harness alone, or a widened tested range is a patch. `callva/harness_runner/version.py` is the one home of the number.

## 13. Later

Progress rendering helpers, if two consumers end up writing the same one. Cost lookup for codex by token price table, if anyone needs a number rather than `None`. A parent watch in the launcher, if a crashed caller's orphaned tree becomes a real problem.

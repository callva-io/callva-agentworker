# Design

`callva-agentworker` runs one headless turn of a coding agent and hands back one result. It exists because the same fifty lines of launch-and-parse code had been written nine times across one owner's tools, each with a different bug, and a tenth was about to be written.

## 1. Scope

One turn: a prompt goes in, an engine runs to its end or its deadline, one `Result` comes out. The library launches the engine with the flags that make a fence real, keeps the process under control, reads the engine's own report tolerantly, and classifies a failure by what the engine said. That is the whole job.

### Non-goals

It does not schedule, queue, retry, or loop. It holds no ledger, no session store, no conversation memory. It renders no progress; it hands events to a callback and the caller renders. It does not know what a task, a message or a job is. It never chooses a model or a fence for the caller: a profile is explicit or the engine's own default applies.

## 2. Names

The distribution is `callva-agentworker` and the import path is `callva.agentworker`: the distribution name is the import path with a dash, the same rule `callva-livekit` follows, and `callva` is a namespace package with no `__init__.py` so the two coexist in one environment. The three nouns a caller uses are `Profile` (how to run), `Session` (which conversation), and `Result` (what came back). `run()` is the one verb. `probe()` answers whether an engine is present.

## 3. Engines

`claude` is Claude Code in print mode. `codex` is the Codex CLI in exec mode. An engine is named by string in the profile; the binary is resolved on the caller's `PATH` first, then in the places a login shell would have added and a launchd job does not: `~/.local/bin`, fnm and nvm node directories, Homebrew.

## 4. Profile

A `Profile` is a frozen record of how one engine is run. Its fields and their meaning:

| Field | Meaning |
|---|---|
| `engine` | `claude` or `codex`. |
| `fence` | `read`, `write` or `act`; see section 6. |
| `model` | passed through; `None` leaves the engine's default. |
| `effort` | passed through as the engine's reasoning-effort setting; `None` leaves the default. |
| `service_tier` | codex only; ignored by claude. |
| `timeout_seconds` | the deadline; the whole process tree is killed when it passes. |
| `budget_usd` | claude only; the engine ends the turn when its own estimate crosses it. |
| `allow_tools` | extra tool patterns a fenced turn may use without prompting, in the engine's own syntax, such as `Bash(tasks:*)`. |
| `env` | an `EnvPolicy`: which inherited variables reach the engine, which are removed, which are set. |
| `extra_args` | appended to the command line verbatim; the escape hatch for a flag the profile does not model. |

`Profile.from_dict()` validates against `profile.schema.json`, which ships in the package so that every consumer's configuration file is checked by the same rule. Unknown keys are refused.

### Environment

The engine inherits the caller's environment through the policy: an optional allow-list of names or globs keeps only those; a deny-list removes names or globs; a set map adds or overrides. The default policy removes only the markers that would make Claude Code think it is running inside another Claude Code session. The binary is found in the caller's `PATH` before the policy is applied and is invoked by absolute path, so an allow-list that omits `PATH` still launches.

## 5. Session

`Session.fresh()` starts a new conversation. On claude the library generates the id before launch and pins it with `--session-id`, so a turn that is killed is still addressable. On codex the id cannot be chosen; it is learned from the first `thread.started` event and reported even when the turn is later killed. `Session.pinned(id)` lets the caller choose the id; it is claude-only and refused on codex. `Session.resume(id)` continues an existing conversation on either engine.

## 6. Fences

A fence is what the turn can do, enforced by the engine's own mechanism, never by the prompt.

| Fence | claude | codex |
|---|---|---|
| `read` | built-in tools limited to `Read`, `Glob`, `Grep` with `--tools`; MCP configuration emptied and pinned so no server on the machine hands tools back; plan mode. With `allow_tools`, the named tools are added to the built-in set, pre-approved, and permission mode becomes `default` so everything else stays denied. | `sandbox_mode="read-only"` with approvals never, set through config overrides because the sandbox flag is absent on `resume`. `allow_tools` has no meaning here: a read-only sandbox cannot let one command write. |
| `write` | `acceptEdits`: file edits inside the working directory need no approval; shell commands run only when named in `allow_tools`. | `sandbox_mode="workspace-write"`, approvals never. |
| `act` | `bypassPermissions`. | `--dangerously-bypass-approvals-and-sandbox`, plus the hook-trust bypass when this codex build has it, probed once per binary. |

A caller that needs a fence shape beyond these three, such as a settings-file sandbox, builds it from `write` or `act` plus `extra_args`.

## 7. Running

The process starts in its own session so that a deadline or a cancel kills the whole tree, not just the parent. Stdout and stderr are drained on threads. The prompt goes by stdin unless the caller asks for argv. Every line of stdout that parses as JSON is handed to `on_event` while the turn runs, so a caller can render progress; on claude this switches the output to the streamed format, on codex the stream is always there. A `threading.Event` passed as `cancel` ends the turn early.

## 8. Reading

Claude answers with one JSON document, and hooks configured on the machine may print other JSON documents before or after it. The reader scans every document on stdout and takes the one whose `type` is `result`. From it: `result` as the answer, `structured_output` when a schema was given, `session_id`, `total_cost_usd`, `duration_ms`, `num_turns`, the four token counts from `usage`, the model actually used from `modelUsage`, `permission_denials`, and `subtype` with `is_error` as the verdict.

Codex answers with a stream of JSONL events and writes the final message to a file the library names. From the stream: `thread.started` gives the thread id, `turn.completed` gives usage, `turn.failed` and `error` events give the failure sentence, and the last `agent_message` item is the answer when the file is empty. Cost is `None` under ChatGPT authentication because codex does not report one.

A structured answer is requested through the engine's native flag. When a schema was given and the engine returned no structured field, the answer text is parsed as JSON; if that fails, the turn is an `invalid_output` failure with the text kept.

## 9. Result

| Field | Meaning |
|---|---|
| `ok` | the engine confirmed a completed turn: claude `subtype == "success"` and `is_error` false; codex `turn.completed` seen, no `turn.failed`, and a non-empty answer. |
| `answer` | the final text, possibly empty on failure. |
| `structured` | the parsed structured answer, or `None`. |
| `session_id` | claude session id or codex thread id; set whenever it is known, including after a kill. |
| `model` | the model that actually ran when the engine reports it, else the requested one, else `None`. |
| `cost_usd`, `duration_ms`, `num_turns`, `tokens` | as reported; `None` where the engine does not say. |
| `permission_denials` | claude's list, empty on codex. |
| `failure` | `None` when `ok`; otherwise a kind and the engine's own sentence. |
| `exit_code` | the process exit code, or `None` if it was killed before exiting. |
| `stderr_tail` | the last lines of stderr, for a person. |
| `command` | the argv that ran, with an argv prompt replaced by a placeholder. |
| `raw` | the result document (claude) or the events and final text (codex), for anything this table left out. |

## 10. Failure kinds

`quota`: the subscription or rate limit is spent; the turn can be retried later without changing anything. `model_refused`: the engine will not run this model; retrying changes nothing. `not_authenticated`: no login or an invalid key. `timeout`: the deadline passed and the tree was killed. `cancelled`: the caller's event was set. `binary_missing`: no engine found. `max_turns`, `budget`: the engine ended the turn on its own limit. `invalid_output`: a schema was required and nothing parsed. `error`: the engine reported a failure this table does not name; the sentence is in `message`. `crash`: the process exited non-zero without a report, or exited zero with no report at all.

Classification reads the engine's sentence in a fixed order: quota before model refusal, because a spent subscription on one model says both, and only one of them is a pause.

## 11. Constraints worth knowing

The cost claude reports is its own estimate and includes subagents; a turn that dies reports no cost at all, so an accumulated total is a floor. Codex under ChatGPT authentication reports tokens but no cost. A claude `read` fence with `allow_tools` runs in `default` permission mode, not plan mode, so the model is not told it is planning. The codex `read` sandbox also has no network unless the caller's codex configuration grants it, which matters when the allowed work is a CLI that talks to a database.

## 12. Versioning

SemVer with the 0.x rule: the minor is the breaking position. A changed field meaning, a removed flag or a changed default is a minor; an added result field, an added profile field with a `None` default, or a newly supported engine option is a patch. `callva/agentworker/version.py` is the one home of the number.

## 13. Later

Progress rendering helpers, if two consumers end up writing the same one. A settings-file sandbox for claude as a fourth fence, once a second consumer needs it. Cost lookup for codex by token price table, if anyone needs a number rather than `None`.

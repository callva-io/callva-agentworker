"""Claude Code in print mode: the command line, and the result document."""

from __future__ import annotations

import json
from typing import Any

from .profile import Profile
from .result import Tokens

READ_TOOLS = ("Read", "Glob", "Grep")
EMPTY_MCP = '{"mcpServers":{}}'


def _base_tool(pattern: str) -> str:
    return pattern.split("(", 1)[0].strip()


def fence_args(profile: Profile) -> list[str]:
    extras = list(profile.allow_tools)
    if profile.fence == "read":
        tools = list(READ_TOOLS)
        for pattern in extras:
            base = _base_tool(pattern)
            if base and base not in tools:
                tools.append(base)
        allowed = list(READ_TOOLS) + extras
        # --tools decides which built-in tools exist; --allowedTools which need no
        # prompt. Plan mode is the model-facing signal when nothing beyond reading
        # is allowed; with extras, default mode keeps everything unnamed denied.
        mode = "default" if extras else "plan"
        return ["--tools", ",".join(tools), "--allowedTools", ",".join(allowed),
                "--permission-mode", mode, "--strict-mcp-config", "--mcp-config", EMPTY_MCP]
    if profile.fence == "write":
        args = ["--permission-mode", "acceptEdits"]
        if extras:
            args += ["--allowedTools", ",".join(extras)]
        return args
    return ["--permission-mode", "bypassPermissions"]


def build_command(
    binary: str,
    profile: Profile,
    *,
    prompt: str,
    prompt_via: str,
    session_id: str | None,
    resume_id: str | None,
    schema_text: str | None,
    stream: bool,
    name: str | None,
) -> list[str]:
    cmd = [binary, "-p"]
    if prompt_via == "argv":
        cmd.append(prompt)
    cmd += ["--output-format", "stream-json" if stream else "json"]
    if stream:
        cmd.append("--verbose")
    if profile.model:
        cmd += ["--model", profile.model]
    if profile.effort:
        cmd += ["--effort", profile.effort]
    if resume_id:
        cmd += ["--resume", resume_id]
    elif session_id:
        cmd += ["--session-id", session_id]
    if name:
        cmd += ["--name", name]
    if profile.budget_usd is not None:
        cmd += ["--max-budget-usd", str(profile.budget_usd)]
    if schema_text:
        cmd += ["--json-schema", schema_text]
    cmd += fence_args(profile)
    cmd += list(profile.extra_args)
    return cmd


def _brace_documents(text: str):
    """Top-level {...} chunks of `text` that parse as JSON objects."""
    depth = 0
    start = None
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                chunk = text[start:index + 1]
                start = None
                try:
                    obj = json.loads(chunk)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    yield obj


def documents(stdout_lines: list[str]) -> list[dict]:
    """Every JSON object on stdout, one per line first, then by brace scan.

    Hooks configured on the machine print their own JSON around the result, and
    some print it pretty, so both readings are needed.
    """
    docs: list[dict] = []
    unparsed: list[str] = []
    for line in stdout_lines:
        stripped = line.strip()
        if not stripped.startswith("{"):
            unparsed.append(line)
            continue
        try:
            obj = json.loads(stripped)
        except ValueError:
            unparsed.append(line)
            continue
        if isinstance(obj, dict):
            docs.append(obj)
        else:
            unparsed.append(line)
    if unparsed:
        docs.extend(_brace_documents("\n".join(unparsed)))
    return docs


def result_document(stdout_lines: list[str]) -> dict | None:
    docs = documents(stdout_lines)
    for doc in reversed(docs):
        if doc.get("type") == "result":
            return doc
    for doc in reversed(docs):
        if {"result", "is_error", "subtype"} & set(doc):
            return doc
    return None


def _model_from_usage(doc: dict) -> str | None:
    usage = doc.get("modelUsage")
    if not isinstance(usage, dict) or not usage:
        return None
    best = None
    best_tokens = -1
    for model, counts in usage.items():
        tokens = counts.get("outputTokens", 0) if isinstance(counts, dict) else 0
        if tokens > best_tokens:
            best, best_tokens = model, tokens
    return best


def read(doc: dict) -> dict[str, Any]:
    usage = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
    answer = doc.get("result")
    return {
        "answer": (answer if isinstance(answer, str)
                   else "" if answer is None else json.dumps(answer)),
        "structured": doc.get("structured_output"),
        "session_id": doc.get("session_id"),
        "cost_usd": doc.get("total_cost_usd"),
        "duration_ms": doc.get("duration_ms"),
        "num_turns": doc.get("num_turns"),
        "tokens": Tokens(
            input=usage.get("input_tokens"),
            output=usage.get("output_tokens"),
            cache_read=usage.get("cache_read_input_tokens"),
            cache_creation=usage.get("cache_creation_input_tokens"),
        ),
        "model": _model_from_usage(doc),
        "permission_denials": tuple(doc.get("permission_denials") or ()),
        "subtype": doc.get("subtype"),
        "is_error": bool(doc.get("is_error")),
    }

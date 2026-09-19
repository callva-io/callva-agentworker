"""Read what an engine said about a failure and name its kind.

The regexes and the unwrapping were first written for a messaging daemon that
had to tell a spent subscription from a wrong answer; they are kept here with
the same order of authority: a spent quota is read before a refused model,
because a subscription spent on one model says both, and only one of those is
a pause that can be waited out.
"""

from __future__ import annotations

import json
import re

from .result import FailureKind

QUOTA_RE = re.compile(
    r"usage limit|rate.?limit|quota|too many requests|\b429\b|insufficient_quota"
    r"|limit reached|limit will reset|resets? (at|in)\b|hit your limit",
    re.IGNORECASE,
)

MODEL_REFUSED_RE = re.compile(
    r"\bmodel_not_found\b"
    r"|\b(?:unknown|unsupported|unrecognized|unrecognised|invalid)[ _-]model\b"
    r"|\bmodel\b[^\n]{0,100}?"
    r"(?:does not exist|do not exist|may not exist|not have access"
    r"|requires a newer version|is not supported|is not available)",
    re.IGNORECASE,
)

NOT_AUTHENTICATED_RE = re.compile(
    r"not logged in|please run /login|run `?claude login|invalid api key|api key.{0,20}invalid"
    r"|authentication_error|\b401\b|\bunauthorized\b|not authenticated|login required"
    r"|no api key|codex login",
    re.IGNORECASE,
)

SUBTYPE_KINDS = {
    "error_max_turns": FailureKind.MAX_TURNS,
    "error_max_budget_usd": FailureKind.BUDGET,
    "error_max_budget": FailureKind.BUDGET,
}


def unwrap_engine_message(text: str | None) -> str:
    """The sentence inside an engine error, when the engine wrapped one.

    Codex forwards the provider's HTTP error verbatim, so `message` is often a
    JSON document whose own `error.message` is the only part a person can read.
    """
    value = (text or "").strip()
    for _ in range(3):
        if not (value.startswith("{") and value.endswith("}")):
            break
        try:
            obj = json.loads(value)
        except ValueError:
            break
        if not isinstance(obj, dict):
            break
        inner = obj.get("error")
        if isinstance(inner, dict) and inner.get("message"):
            value = str(inner["message"]).strip()
            continue
        if isinstance(inner, str) and inner.strip():
            value = inner.strip()
            continue
        if obj.get("message"):
            value = str(obj["message"]).strip()
            continue
        break
    return value


def is_quota(message: str | None) -> bool:
    return bool(QUOTA_RE.search(str(message or "")))


def is_model_refused(message: str | None) -> bool:
    text = str(message or "")
    return bool(MODEL_REFUSED_RE.search(text)) and not is_quota(text)


def is_not_authenticated(message: str | None) -> bool:
    text = str(message or "")
    return bool(NOT_AUTHENTICATED_RE.search(text)) and not is_quota(text)


def classify(
    message: str | None,
    *,
    subtype: str | None = None,
    timed_out: bool = False,
    cancelled: bool = False,
    had_report: bool = True,
) -> FailureKind:
    """Name the kind of a failure from what is known about it.

    `had_report` is false when the process ended without the engine's own
    result document, which is the one case where nothing the engine said can
    be read and the kind is `crash`.
    """
    if cancelled:
        return FailureKind.CANCELLED
    if timed_out:
        return FailureKind.TIMEOUT
    if subtype in SUBTYPE_KINDS:
        return SUBTYPE_KINDS[subtype]
    if is_quota(message):
        return FailureKind.QUOTA
    if is_model_refused(message):
        return FailureKind.MODEL_REFUSED
    if is_not_authenticated(message):
        return FailureKind.NOT_AUTHENTICATED
    if not had_report:
        return FailureKind.CRASH
    return FailureKind.ERROR

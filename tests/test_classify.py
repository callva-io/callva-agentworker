import json

from callva.agentworker import FailureKind
from callva.agentworker.classify import classify, unwrap_engine_message


def test_quota_before_model_refusal():
    assert classify("Rate limit reached for model gpt-x; too many requests") == FailureKind.QUOTA
    assert classify("You've hit your usage limit. Resets at 3pm") == FailureKind.QUOTA
    assert classify("api_error_status 429") == FailureKind.QUOTA


def test_model_refused_and_auth():
    refused = "The model `claude-9` does not exist or you do not have access"
    assert classify(refused) == FailureKind.MODEL_REFUSED
    assert classify("model_not_found: gpt-99") == FailureKind.MODEL_REFUSED
    assert classify("Not logged in. Please run /login.") == FailureKind.NOT_AUTHENTICATED
    assert classify("Invalid API key · Fix external API key") == FailureKind.NOT_AUTHENTICATED


def test_http_status_before_sentence():
    assert classify("API Error", http_status=429) == FailureKind.QUOTA
    assert classify("API Error", http_status=401) == FailureKind.NOT_AUTHENTICATED
    assert classify("API Error", http_status=500) == FailureKind.ERROR


def test_subtypes_flags_and_fallbacks():
    assert classify("", subtype="error_max_turns") == FailureKind.MAX_TURNS
    assert classify("", subtype="error_max_budget_usd") == FailureKind.BUDGET
    assert classify("anything", timed_out=True) == FailureKind.TIMEOUT
    assert classify("anything", cancelled=True, timed_out=True) == FailureKind.CANCELLED
    assert classify("exit 2", had_report=False) == FailureKind.CRASH
    assert classify("something odd happened") == FailureKind.ERROR


def test_unwrap_nested_provider_error():
    inner = json.dumps({"error": {"message": "inner sentence"}})
    wrapped = json.dumps({"error": {"message": inner}})
    assert unwrap_engine_message(wrapped) == "inner sentence"
    assert unwrap_engine_message("plain") == "plain"
    assert unwrap_engine_message('{"message": "top"}') == "top"

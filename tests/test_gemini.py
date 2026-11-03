"""Gemini REST boundary tested locally with synthetic audit data only."""

import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from mod1_auth.ai_adapter import AIAdapter
from mod1_auth.identity_service import IdentityError


def configure(settings, **updates):
    return type(settings)(
        **(
            settings.model_dump()
            | {"ai_provider": "gemini", "gemini_api_key": "test-only-key"}
            | updates
        ),
        _env_file=None,
    )


def proposal():
    return {
        "summary": "Sem anomalias",
        "justification": "Nenhuma ação fundamentada",
        "evidence": [],
        "suggestions": [],
    }


def envelope(output=None):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [{"text": json.dumps(proposal() if output is None else output)}]
                },
            }
        ]
    }


def test_gemini_request_and_empty_response(settings):
    settings = configure(settings, ai_base_url="https://generic.example.com", ai_model="ignored")
    context = {"audit_events": [], "users": []}

    def handler(request):
        assert str(request.url) == (
            "https://generativelanguage.googleapis.com/v1beta/"
            "models/gemini-3.5-flash-lite:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "test-only-key"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert json.loads(body["contents"][0]["parts"][0]["text"]) == {
            "kind": "access_anomalies",
            "context": context,
        }
        instructions = body["systemInstruction"]["parts"][0]["text"]
        assert "não confiáveis" in instructions and "evidence_ids" in instructions
        config = body["generationConfig"]
        assert config["candidateCount"] == 1 and config["maxOutputTokens"] == 4096
        text = config["responseFormat"]["text"]
        assert text["mimeType"] == "APPLICATION_JSON"
        assert text["schema"]["properties"]["suggestions"]["type"] == "array"
        assert "tools" not in body
        return httpx.Response(200, json=envelope())

    adapter = AIAdapter(settings, httpx.MockTransport(handler))
    assert adapter.generate(context) == proposal()
    assert (adapter.provider, adapter.model, adapter.simulated) == (
        "gemini",
        "gemini-3.5-flash-lite",
        False,
    )
    assert "test-only-key" not in repr(settings) and "gemini_api_key" not in repr(settings)


@pytest.mark.parametrize(
    "change",
    [
        {"gemini_api_base_url": "https://evil.example/v1beta"},
        {"gemini_api_base_url": "https://generativelanguage.googleapis.com:444/v1beta"},
        {"gemini_api_base_url": "http://generativelanguage.googleapis.com/v1beta"},
        {"gemini_api_base_url": "https://test@generativelanguage.googleapis.com/v1beta"},
        {"gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta?key=x"},
        {"gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta#fragment"},
        {"gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta/../evil"},
        {"gemini_api_base_url": "http://127.0.0.1:8080/%2e%2e"},
        {"gemini_api_base_url": "http://127.0.0.1:bad/v1beta"},
        {"gemini_api_base_url": "http://127.0.0.1:65536/v1beta"},
        {"gemini_model": "models/gemini"},
        {"gemini_model": "gemini?key=secret"},
        {"gemini_model": "gemini%2Fsecret"},
        {"gemini_timeout_seconds": 31},
        {"gemini_timeout_seconds": 0},
        {"gemini_max_output_tokens": 8193},
        {"gemini_max_output_tokens": 255},
        {"ai_simulated": True},
    ],
)
def test_gemini_configuration_rejects_unsafe_values(settings, change):
    with pytest.raises(ValidationError):
        configure(settings, **change)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:7654/v1beta", "http://[::1]:7654/v1beta", "http://localhost:7654/v1beta"],
)
def test_gemini_loopback_override(settings, url):
    configured = configure(settings, gemini_api_base_url=url)
    assert configured.gemini_api_base_url == url


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, text="test-only-key"),
        httpx.Response(500, text="test-only-key"),
        httpx.Response(302, headers={"location": "https://evil.example"}),
        httpx.Response(200, text="not JSON"),
        httpx.Response(200, json={"candidates": []}),
        httpx.Response(200, json={"candidates": [envelope()["candidates"][0]] * 2}),
        httpx.Response(200, json=envelope() | {"promptFeedback": {"blockReason": "SAFETY"}}),
        httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS", "content": {}}]}),
        httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"functionCall": {"name": "delete_users"}}]},
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "[]"}]}}]},
        ),
        httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": '{"summary":'}]}}
                ]
            },
        ),
        httpx.Response(200, content=b" " * 262145),
    ],
)
def test_gemini_failure_is_sanitized_without_retries(settings, response):
    calls = []

    def handler(request):
        calls.append(request)
        return response

    with pytest.raises(IdentityError) as error:
        AIAdapter(configure(settings), httpx.MockTransport(handler)).generate({})
    assert error.value.status == 503
    assert "test-only-key" not in str(error.value)
    assert len(calls) == 1


def test_gemini_timeout_and_missing_key(settings):
    def timeout(request):
        raise httpx.ReadTimeout("test-only-key", request=request)

    for configured, handler in [
        (configure(settings), timeout),
        (
            configure(settings, gemini_api_key=None),
            lambda request: pytest.fail("Missing key must not send HTTP"),
        ),
    ]:
        with pytest.raises(IdentityError) as error:
            AIAdapter(configured, httpx.MockTransport(handler)).generate({})
        assert error.value.status == 503 and "test-only-key" not in str(error.value)


def test_gemini_context_bound_before_network(settings):
    with pytest.raises(IdentityError):
        AIAdapter(
            configure(settings),
            httpx.MockTransport(
                lambda request: pytest.fail("Oversized context must not send HTTP")
            ),
        ).generate({"text": "é" * 131073})


def test_mutated_model_cannot_change_request_path(settings):
    configured = configure(settings)
    configured.gemini_model = "../../other:generateContent?key=secret"
    with pytest.raises(IdentityError):
        AIAdapter(
            configured,
            httpx.MockTransport(lambda request: pytest.fail("Invalid model must not send HTTP")),
        ).generate({})


def test_gemini_valid_typed_suggestion_and_thought_filter(settings):
    event, user = str(uuid4()), str(uuid4())
    output = proposal() | {
        "evidence": [event],
        "suggestions": [
            {
                "user_id": user,
                "action": "review_access",
                "reason": "Revisar evento real",
                "evidence_ids": [event],
            }
        ],
    }
    payload = envelope(output)
    payload["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "hidden"})
    assert (
        AIAdapter(
            configure(settings),
            httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        ).generate({})
        == output
    )


@pytest.mark.parametrize("location", ["promptFeedback", "candidate"])
def test_gemini_rejects_blocked_rating_even_with_stop(settings, location):
    payload = envelope()
    if location == "promptFeedback":
        payload["promptFeedback"] = {"safetyRatings": [{"blocked": True}]}
    else:
        payload["candidates"][0]["safetyRatings"] = [{"blocked": True}]
    with pytest.raises(IdentityError) as error:
        AIAdapter(
            configure(settings),
            httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        ).generate({})
    assert error.value.status == 503


def test_gemini_rejects_non_boolean_thought_marker(settings):
    payload = envelope()
    payload["candidates"][0]["content"]["parts"][0]["thought"] = "true"
    with pytest.raises(IdentityError) as error:
        AIAdapter(
            configure(settings),
            httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        ).generate({})
    assert error.value.status == 503


def test_gemini_accepts_final_text_with_thought_signature(settings):
    payload = envelope()
    payload["candidates"][0]["content"]["parts"][0]["thoughtSignature"] = "synthetic-signature"
    assert (
        AIAdapter(
            configure(settings),
            httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        ).generate({})
        == proposal()
    )

from __future__ import annotations

import pytest

import novel_agent.app.llm as llm_module
from novel_agent.app.llm import InvalidJSONResponseError, JsonModelClient, ModelSettings


def _build_client(monkeypatch: pytest.MonkeyPatch) -> JsonModelClient:
    monkeypatch.setattr(JsonModelClient, "_build_model", lambda self: object())
    return JsonModelClient(
        ModelSettings(
            model_type="OpenAIModel",
            model_name="test-model",
            api_key="test-key",
        )
    )


def test_generate_json_retries_invalid_json_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)
    responses = iter(
        [
            "this is not json",
            '```json\n{"chapter": 1, "title": "第一章"}\n```',
        ]
    )

    monkeypatch.setattr(client, "generate_text", lambda **_: next(responses))
    monkeypatch.setattr(llm_module.time, "sleep", lambda *_: None)

    payload, raw_text = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        fallback_factory=lambda: {"fallback": True},
    )

    assert payload == {"chapter": 1, "title": "第一章"}
    assert '"chapter": 1' in raw_text


def test_generate_json_raises_after_exhausting_invalid_json_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)
    responses = iter(["bad-1", "bad-2", "bad-3"])

    monkeypatch.setattr(client, "generate_text", lambda **_: next(responses))
    monkeypatch.setattr(llm_module.time, "sleep", lambda *_: None)

    with pytest.raises(InvalidJSONResponseError) as exc_info:
        client.generate_json(
            system_prompt="system",
            user_prompt="user",
            fallback_factory=lambda: {"fallback": True},
        )

    assert exc_info.value.attempts == 3
    assert exc_info.value.raw_text == "bad-3"


def test_generate_json_ignores_fallback_on_error_for_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)
    responses = iter(["bad-1", "bad-2", "bad-3"])

    monkeypatch.setattr(client, "generate_text", lambda **_: next(responses))
    monkeypatch.setattr(llm_module.time, "sleep", lambda *_: None)

    with pytest.raises(InvalidJSONResponseError):
        client.generate_json(
            system_prompt="system",
            user_prompt="user",
            fallback_factory=lambda: {"fallback": True},
            use_fallback_on_error=True,
        )

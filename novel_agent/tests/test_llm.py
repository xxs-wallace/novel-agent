from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from novel_agent.app.llm import JsonModelClient, ModelSettings


def test_json_model_client_retries_transient_generation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FlakyModel:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary timeout")
            return SimpleNamespace(content="ok", raw=None)

    model = FlakyModel()
    monkeypatch.setattr(JsonModelClient, "_build_model", lambda _self: model)
    client = JsonModelClient(
        ModelSettings(
            model_type="FakeModel",
            model_name="fake",
            request_retry_attempts=2,
            request_retry_backoff_seconds=0,
        )
    )

    assert client.generate_text(system_prompt="system", user_prompt="user") == "ok"
    assert model.calls == 2


def test_json_model_client_raises_after_retry_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenModel:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            self.calls += 1
            raise TimeoutError("still timing out")

    model = BrokenModel()
    monkeypatch.setattr(JsonModelClient, "_build_model", lambda _self: model)
    client = JsonModelClient(
        ModelSettings(
            model_type="FakeModel",
            model_name="fake",
            request_retry_attempts=2,
            request_retry_backoff_seconds=0,
        )
    )

    with pytest.raises(TimeoutError):
        client.generate_text(system_prompt="system", user_prompt="user")
    assert model.calls == 2


def test_json_model_client_applies_outer_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class HangingModel:
        def generate(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            time.sleep(2)
            return SimpleNamespace(content="too-late", raw=None)

    monkeypatch.setattr(JsonModelClient, "_build_model", lambda _self: HangingModel())
    client = JsonModelClient(
        ModelSettings(
            model_type="FakeModel",
            model_name="fake",
            timeout_seconds=1,
            request_retry_attempts=1,
            request_retry_backoff_seconds=0,
        )
    )

    started_at = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out after 1s"):
        client.generate_text(system_prompt="system", user_prompt="user")
    assert time.monotonic() - started_at < 1.8


def test_json_model_client_generate_text_allows_timeout_override(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_timeouts: list[int | None] = []

    class RecordingClient(JsonModelClient):
        def _generate_with_timeout(self, **kwargs: object) -> SimpleNamespace:  # type: ignore[override]
            seen_timeouts.append(kwargs.get("timeout_seconds"))  # type: ignore[arg-type]
            return SimpleNamespace(content="ok", raw=None)

    monkeypatch.setattr(JsonModelClient, "_build_model", lambda _self: object())
    client = RecordingClient(
        ModelSettings(
            model_type="FakeModel",
            model_name="fake",
            timeout_seconds=1,
            request_retry_attempts=1,
            request_retry_backoff_seconds=0,
        )
    )

    assert client.generate_text(system_prompt="system", user_prompt="user", timeout_seconds=7) == "ok"
    assert seen_timeouts == [7]


def test_generate_json_does_not_replace_transport_failures_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenModel:
        def generate(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            raise TimeoutError("transport timeout")

    monkeypatch.setattr(JsonModelClient, "_build_model", lambda _self: BrokenModel())
    client = JsonModelClient(
        ModelSettings(
            model_type="FakeModel",
            model_name="fake",
            request_retry_attempts=1,
            request_retry_backoff_seconds=0,
        )
    )

    with pytest.raises(TimeoutError):
        client.generate_json(
            system_prompt="system",
            user_prompt="user",
            fallback_factory=lambda: {"fallback": True},
            use_fallback_on_error=True,
        )


def test_json_model_client_retries_with_thinking_disabled_after_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenThinkingModel:
        def generate(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            raise TimeoutError("thinking request timed out")

    class DisabledThinkingModel:
        def generate(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(content="ok-without-thinking", raw=None)

    built_thinking_modes: list[str | None] = []

    def fake_build_model(self: JsonModelClient, settings: ModelSettings | None = None):  # type: ignore[no-untyped-def]
        resolved = settings or self.settings
        built_thinking_modes.append(resolved.thinking)
        if resolved.thinking is None:
            assert resolved.reasoning_effort is None
            assert resolved.include_reasoning_content is False
            return DisabledThinkingModel()
        return BrokenThinkingModel()

    monkeypatch.setattr(JsonModelClient, "_build_model", fake_build_model)
    client = JsonModelClient(
        ModelSettings(
            model_type="OpenAIModel",
            model_name="fake",
            api_key="test-key",
            request_retry_attempts=1,
            request_retry_backoff_seconds=0,
            retry_without_thinking_on_failure=True,
            thinking="enabled",
            reasoning_effort="high",
            include_reasoning_content=True,
        )
    )

    assert client.generate_text(system_prompt="system", user_prompt="user") == "ok-without-thinking"
    assert built_thinking_modes == ["enabled", None]


def test_json_model_client_can_disable_thinking_for_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingModel:
        def __init__(self, label: str | None) -> None:
            self.label = label

        def generate(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(content=f"ok:{self.label}", raw=None)

    built_thinking_modes: list[str | None] = []

    def fake_build_model(self: JsonModelClient, settings: ModelSettings | None = None):  # type: ignore[no-untyped-def]
        resolved = settings or self.settings
        built_thinking_modes.append(resolved.thinking)
        if resolved.thinking == "disabled":
            assert resolved.reasoning_effort is None
            assert resolved.include_reasoning_content is False
        return RecordingModel(resolved.thinking)

    monkeypatch.setattr(JsonModelClient, "_build_model", fake_build_model)
    client = JsonModelClient(
        ModelSettings(
            model_type="OpenAIModel",
            model_name="fake",
            api_key="test-key",
            request_retry_attempts=1,
            thinking="enabled",
            reasoning_effort="high",
            include_reasoning_content=True,
        )
    )

    assert client.generate_text(system_prompt="system", user_prompt="user", thinking="disabled") == "ok:None"
    assert client.generate_text(system_prompt="system", user_prompt="user") == "ok:enabled"
    assert built_thinking_modes == ["enabled", None]


def test_openai_model_uses_client_timeout_and_disables_nested_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import smolagents.models as smolagents_models

    monkeypatch.setattr(smolagents_models, "OpenAIModel", FakeOpenAIModel)
    JsonModelClient(
        ModelSettings(
            model_type="OpenAIModel",
            model_name="deepseek-test",
            api_key="test-key",
            timeout_seconds=42,
        )
    )

    assert captured["timeout"] == 42
    assert captured["client_kwargs"] == {"timeout": 42, "max_retries": 0}


def test_openai_model_omits_disabled_thinking_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import smolagents.models as smolagents_models

    monkeypatch.setattr(smolagents_models, "OpenAIModel", FakeOpenAIModel)
    JsonModelClient(
        ModelSettings(
            model_type="OpenAIModel",
            model_name="deepseek-test",
            api_key="test-key",
            thinking="disabled",
            reasoning_effort=None,
            include_reasoning_content=False,
        )
    )

    assert captured["extra_body"] is None
    assert captured["reasoning_effort"] is None
    assert captured["include_reasoning_content"] is False

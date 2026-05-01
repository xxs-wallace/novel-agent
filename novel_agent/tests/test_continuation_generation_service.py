from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from novel_agent.app.services.continuation_generation_service import (
    ContinuationGenerationResult,
    ContinuationGenerationService,
)
from novel_agent.schemas import RunConfig


def _config(**overrides: object) -> RunConfig:
    data = {
        "prompt": None,
        "model_type": "InferenceClientModel",
        "model_id": "test-model",
        "provider": None,
        "api_base": None,
        "api_key": None,
        "thinking": None,
        "reasoning_effort": None,
        "save_reasoning": True,
        "action_type": "code",
        "tools": ["python_interpreter"],
        "imports": ["json"],
        "verbosity_level": 1,
        "dry_run": False,
    }
    data.update(overrides)
    return RunConfig(**data)


def test_continuation_generation_service_runs_code_agent_and_collects_reasoning(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class _FakeCodeAgent:
        def __init__(self, *, tools, model, additional_authorized_imports, verbosity_level, stream_outputs) -> None:  # type: ignore[no-untyped-def]
            captured["tools"] = tools
            captured["model"] = model
            captured["imports"] = additional_authorized_imports
            captured["verbosity_level"] = verbosity_level
            captured["stream_outputs"] = stream_outputs
            self.memory = SimpleNamespace(
                steps=[
                    SimpleNamespace(
                        model_output_message=SimpleNamespace(
                            reasoning_content="先整理上下文",
                            content="生成的正文",
                        )
                    )
                ]
            )

        def run(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return "生成的正文"

    monkeypatch.setattr(
        "novel_agent.app.services.continuation_generation_service.build_tools",
        lambda tool_names: ["tool:" + name for name in tool_names],
    )
    monkeypatch.setattr(
        "novel_agent.app.services.continuation_generation_service.load_model",
        lambda **kwargs: {"model": kwargs},
    )
    monkeypatch.setattr(
        "novel_agent.app.services.continuation_generation_service.CodeAgent",
        _FakeCodeAgent,
    )

    result = ContinuationGenerationService().generate(
        prompt="继续写这一段。",
        config=_config(),
    )

    assert isinstance(result, ContinuationGenerationResult)
    assert result.generated_text == "生成的正文"
    assert result.reasoning_steps[0].reasoning_content == "先整理上下文"
    assert result.reasoning_markdown == "先整理上下文\n"
    assert captured["prompt"] == "继续写这一段。"
    assert captured["tools"] == ["tool:python_interpreter"]
    assert captured["imports"] == ["json"]
    assert captured["stream_outputs"] is False


def test_continuation_generation_service_uses_direct_model_generation_when_no_tools(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class _FakeOpenAIModel:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            captured["model_kwargs"] = kwargs

        def generate(self, messages):  # type: ignore[no-untyped-def]
            captured["messages"] = messages
            return SimpleNamespace(
                content="tool calling output",
                reasoning_content="先构思再续写",
                raw=None,
            )

    monkeypatch.setattr(
        "novel_agent.app.services.continuation_generation_service.OpenAIModel",
        _FakeOpenAIModel,
    )

    result = ContinuationGenerationService().generate(
        prompt="继续写。",
        config=_config(
            model_type="OpenAIModel",
            thinking="enabled",
            reasoning_effort="high",
            action_type="tool_calling",
            save_reasoning=True,
            tools=[],
            imports=[],
        ),
    )

    assert result.generated_text == "tool calling output"
    assert result.reasoning_steps[0].reasoning_content == "先构思再续写"
    assert result.reasoning_steps[0].step_type == "DirectModelResponse"
    assert captured["model_kwargs"] == {
        "model_id": "test-model",
        "api_base": None,
        "api_key": None,
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
        "include_reasoning_content": True,
    }
    messages = cast(list[Any], captured["messages"])
    assert len(messages) == 1
    assert messages[0].content == "继续写。"


def test_continuation_generation_service_rejects_thinking_without_openai_model() -> None:
    with pytest.raises(ValueError, match="thinking/reasoning_effort requires OpenAIModel"):
        ContinuationGenerationService().generate(
            prompt="继续写。",
            config=_config(thinking="enabled"),
        )

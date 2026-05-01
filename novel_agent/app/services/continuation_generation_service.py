from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smolagents import CodeAgent, ToolCallingAgent
from smolagents.cli import load_model
from smolagents.models import ChatMessage, MessageRole, OpenAIModel

from ...schemas import RunConfig
from ...tools import build_tools


@dataclass(slots=True)
class ContinuationReasoningStep:
    step_type: str
    reasoning_content: str | None = None
    content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_type": self.step_type,
            "reasoning_content": self.reasoning_content,
            "content": self.content,
        }


@dataclass(slots=True)
class ContinuationGenerationResult:
    generated_text: str
    reasoning_steps: list[ContinuationReasoningStep]
    reasoning_markdown: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_text": self.generated_text,
            "reasoning_steps": [item.to_dict() for item in self.reasoning_steps],
            "reasoning_markdown": self.reasoning_markdown,
        }


class ContinuationGenerationService:
    def generate(
        self,
        *,
        prompt: str,
        config: RunConfig,
    ) -> ContinuationGenerationResult:
        normalized_prompt = str(prompt).strip()
        if not normalized_prompt:
            raise ValueError("prompt is required for continuation generation")
        self._validate_config(config)

        model = self._build_model(config)
        if self._should_generate_direct_text(config):
            response = model.generate(
                [ChatMessage(role=MessageRole.USER, content=normalized_prompt)],
            )
            generated_text = self._extract_chat_message_text(response)
            reasoning_steps = self._collect_chat_message_reasoning(response) if config.save_reasoning else []
        else:
            tools = build_tools(list(config.tools))
            agent = self._build_agent(
                config=config,
                model=model,
                tools=tools,
            )
            output = agent.run(normalized_prompt)
            generated_text = self._normalize_generated_text(output)
            reasoning_steps = self._collect_reasoning_steps(agent) if config.save_reasoning else []
        reasoning_markdown = self._build_reasoning_markdown(reasoning_steps)
        return ContinuationGenerationResult(
            generated_text=generated_text,
            reasoning_steps=reasoning_steps,
            reasoning_markdown=reasoning_markdown,
        )

    def _validate_config(self, config: RunConfig) -> None:
        if (config.thinking or config.reasoning_effort) and config.model_type != "OpenAIModel":
            raise ValueError("thinking/reasoning_effort requires OpenAIModel")

    def _build_model(self, config: RunConfig) -> Any:
        if config.model_type == "OpenAIModel" and (config.thinking or config.reasoning_effort):
            extra_body = {"thinking": {"type": config.thinking}} if config.thinking else None
            return OpenAIModel(
                model_id=config.model_id,
                api_base=config.api_base,
                api_key=config.api_key,
                reasoning_effort=config.reasoning_effort,
                extra_body=extra_body,
                include_reasoning_content=True,
            )
        return load_model(
            model_type=config.model_type,
            model_id=config.model_id,
            api_base=config.api_base,
            api_key=config.api_key,
            provider=config.provider,
        )

    def _should_generate_direct_text(self, config: RunConfig) -> bool:
        return config.action_type == "tool_calling" and not list(config.tools)

    def _build_agent(
        self,
        *,
        config: RunConfig,
        model: Any,
        tools: list[Any],
    ) -> Any:
        if config.action_type == "code":
            return CodeAgent(
                tools=tools,
                model=model,
                additional_authorized_imports=list(config.imports),
                verbosity_level=config.verbosity_level,
                stream_outputs=False,
            )
        return ToolCallingAgent(
            tools=tools,
            model=model,
            verbosity_level=config.verbosity_level,
            stream_outputs=False,
        )

    def _normalize_generated_text(self, output: Any) -> str:
        if output is None:
            return ""
        if isinstance(output, str):
            return output.strip()
        return str(output).strip()

    def _extract_chat_message_text(self, response: Any) -> str:
        content = getattr(response, "content", None)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return "\n".join(parts).strip()
        raw = getattr(response, "raw", None)
        choices = getattr(raw, "choices", None)
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        raw_content = getattr(message, "content", None)
        if isinstance(raw_content, str):
            return raw_content.strip()
        return ""

    def _collect_chat_message_reasoning(self, response: Any) -> list[ContinuationReasoningStep]:
        reasoning = getattr(response, "reasoning_content", None)
        content = getattr(response, "content", None)
        if reasoning is None and content is None:
            return []
        normalized_content = self._extract_chat_message_text(response)
        return [
            ContinuationReasoningStep(
                step_type="DirectModelResponse",
                reasoning_content=str(reasoning) if reasoning is not None else None,
                content=normalized_content or (str(content) if content is not None else None),
            )
        ]

    def _collect_reasoning_steps(self, agent: Any) -> list[ContinuationReasoningStep]:
        steps: list[ContinuationReasoningStep] = []
        memory = getattr(agent, "memory", None)
        raw_steps = getattr(memory, "steps", None)
        if not isinstance(raw_steps, list):
            return steps
        for step in raw_steps:
            message = getattr(step, "model_output_message", None)
            if message is None:
                continue
            reasoning = getattr(message, "reasoning_content", None)
            content = getattr(message, "content", None)
            if reasoning is None and content is None:
                continue
            steps.append(
                ContinuationReasoningStep(
                    step_type=type(step).__name__,
                    reasoning_content=str(reasoning) if reasoning is not None else None,
                    content=str(content) if content is not None else None,
                )
            )
        return steps

    def _build_reasoning_markdown(self, steps: list[ContinuationReasoningStep]) -> str:
        parts = [str(item.reasoning_content or "").strip() for item in steps if str(item.reasoning_content or "").strip()]
        if not parts:
            return ""
        return "\n\n".join(parts).strip() + "\n"

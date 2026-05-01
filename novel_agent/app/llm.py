from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, cast
import time

from smolagents.cli import load_model
from smolagents.models import ChatMessage, MessageRole, OpenAIModel

from .bootstrap import read_api_key
from .utils.json_utils import extract_json_blob

JSON_RETRY_ATTEMPTS = 3


@dataclass(slots=True)
class ModelSettings:
    model_type: str
    model_name: str
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    api_key_file: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.2
    max_output_tokens: int = 8192
    timeout_seconds: int = 120
    thinking: str | None = None
    reasoning_effort: str | None = None
    include_reasoning_content: bool = False
    dry_run: bool = False


class InvalidJSONResponseError(ValueError):
    def __init__(self, *, raw_text: str, attempts: int) -> None:
        self.raw_text = raw_text
        self.attempts = attempts
        preview = raw_text[:1200]
        super().__init__(
            f"Model did not return valid JSON after {attempts} attempts. "
            f"Raw output preview:\n{preview}"
        )


class JsonModelClient:
    def __init__(self, settings: ModelSettings) -> None:
        self.settings = settings
        self.api_key = read_api_key(
            api_key=settings.api_key,
            api_key_file=settings.api_key_file,
            env_name=settings.api_key_env,
        )
        self.model = None if settings.dry_run else self._build_model()

    def _build_model(self):
        if self.settings.model_type == "OpenAIModel":
            extra_body = {"thinking": {"type": self.settings.thinking}} if self.settings.thinking else None
            return OpenAIModel(
                model_id=self.settings.model_name,
                api_base=self.settings.base_url,
                api_key=self.api_key,
                temperature=self.settings.temperature,
                max_tokens=self.settings.max_output_tokens,
                timeout=self.settings.timeout_seconds,
                reasoning_effort=self.settings.reasoning_effort,
                extra_body=extra_body,
                include_reasoning_content=self.settings.include_reasoning_content,
            )
        return load_model(
            model_type=self.settings.model_type,
            model_id=self.settings.model_name,
            api_base=self.settings.base_url,
            api_key=self.api_key,
            provider=self.settings.provider,
        )

    def generate_text(self, *, system_prompt: str, user_prompt: str, fallback_text: str | None = None) -> str:
        if self.settings.dry_run:
            if fallback_text is None:
                raise RuntimeError("Dry-run mode requires fallback_text")
            return fallback_text
        if self.model is None:
            raise RuntimeError("Model client is not initialized")
        messages: list[ChatMessage | dict[str, Any]] = [
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]
        last_text = ""
        for attempt in range(3):
            response = cast(Any, self.model).generate(messages, temperature=self.settings.temperature)
            text = str(response.content or "").strip()
            if not text:
                text = self._extract_text_from_raw_response(response).strip()
            if text:
                return text
            last_text = text
            if attempt < 2:
                time.sleep(1.0)
        return last_text

    def _extract_text_from_raw_response(self, response: Any) -> str:
        raw = getattr(response, "raw", None)
        if raw is None:
            return ""
        choices = getattr(raw, "choices", None)
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None) if not isinstance(item, dict) else item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            return "\n".join(parts)
        return ""

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory: Callable[[], dict[str, Any] | list[Any]],
        use_fallback_on_error: bool = False,
    ) -> tuple[dict[str, Any] | list[Any], str]:
        if self.settings.dry_run:
            payload = fallback_factory()
            return payload, json.dumps(payload, ensure_ascii=False, indent=2)
        raw_text = ""
        last_error: ValueError | None = None
        for attempt in range(JSON_RETRY_ATTEMPTS):
            raw_text = self.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)
            try:
                payload = extract_json_blob(raw_text)
                return payload, raw_text
            except ValueError as exc:
                last_error = exc
                if attempt < JSON_RETRY_ATTEMPTS - 1:
                    time.sleep(1.0)
                    continue
        if use_fallback_on_error:
            payload = fallback_factory()
            return payload, raw_text
        raise InvalidJSONResponseError(raw_text=raw_text, attempts=JSON_RETRY_ATTEMPTS) from last_error

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, cast
import time

from .bootstrap import read_api_key
from .utils.json_utils import extract_json_blob

JSON_RETRY_ATTEMPTS = 3
DEFAULT_REQUEST_RETRY_ATTEMPTS = 3
DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS = 1.0
logger = logging.getLogger(__name__)


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
    request_retry_attempts: int = DEFAULT_REQUEST_RETRY_ATTEMPTS
    request_retry_backoff_seconds: float = DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS
    retry_without_thinking_on_failure: bool = False
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

    def _build_model(self, settings: ModelSettings | None = None):
        settings = settings or self.settings
        if settings.model_type == "OpenAIModel":
            from smolagents.models import OpenAIModel

            extra_body = {"thinking": {"type": settings.thinking}} if settings.thinking else None
            return OpenAIModel(
                model_id=settings.model_name,
                api_base=settings.base_url,
                api_key=self.api_key,
                client_kwargs={
                    "timeout": settings.timeout_seconds,
                    "max_retries": 0,
                },
                temperature=settings.temperature,
                max_tokens=settings.max_output_tokens,
                timeout=settings.timeout_seconds,
                reasoning_effort=settings.reasoning_effort,
                extra_body=extra_body,
                include_reasoning_content=settings.include_reasoning_content,
            )
        from smolagents.cli import load_model

        return load_model(
            model_type=settings.model_type,
            model_id=settings.model_name,
            api_base=settings.base_url,
            api_key=self.api_key,
            provider=settings.provider,
        )

    def generate_text(self, *, system_prompt: str, user_prompt: str, fallback_text: str | None = None) -> str:
        if self.settings.dry_run:
            if fallback_text is None:
                raise RuntimeError("Dry-run mode requires fallback_text")
            return fallback_text
        if self.model is None:
            raise RuntimeError("Model client is not initialized")
        from smolagents.models import ChatMessage, MessageRole

        messages: list[Any | dict[str, Any]] = [
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]
        attempts = max(1, int(self.settings.request_retry_attempts))
        backoff = max(0.0, float(self.settings.request_retry_backoff_seconds))
        prompt_chars = len(system_prompt) + len(user_prompt)

        try:
            text = self._generate_text_with_retries(
                model=self.model,
                messages=messages,
                attempts=attempts,
                backoff=backoff,
                prompt_chars=prompt_chars,
                retry_label="primary",
            )
        except Exception as primary_error:
            if not self._should_retry_without_thinking():
                raise
            logger.warning(
                "LLM request exhausted primary attempts for model=%s; retrying with thinking disabled: %s",
                self.settings.model_name,
                primary_error,
            )
            fallback_settings = self._settings_without_thinking()
            fallback_model = self._build_model(fallback_settings)
            return self._generate_text_with_retries(
                model=fallback_model,
                messages=messages,
                attempts=attempts,
                backoff=backoff,
                prompt_chars=prompt_chars,
                retry_label="thinking_disabled",
            )
        if text or not self._should_retry_without_thinking():
            return text
        logger.warning(
            "LLM returned empty text after primary attempts for model=%s; retrying with thinking disabled",
            self.settings.model_name,
        )
        fallback_settings = self._settings_without_thinking()
        fallback_model = self._build_model(fallback_settings)
        return self._generate_text_with_retries(
            model=fallback_model,
            messages=messages,
            attempts=attempts,
            backoff=backoff,
            prompt_chars=prompt_chars,
            retry_label="thinking_disabled",
        )

    def _generate_text_with_retries(
        self,
        *,
        model: Any,
        messages: list[Any | dict[str, Any]],
        attempts: int,
        backoff: float,
        prompt_chars: int,
        retry_label: str,
    ) -> str:
        last_text = ""
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started_at = time.monotonic()
            try:
                response = cast(Any, model).generate(messages, temperature=self.settings.temperature)
                text = str(response.content or "").strip()
                if not text:
                    text = self._extract_text_from_raw_response(response).strip()
                if text:
                    return text
                last_text = text
                last_error = None
                if attempt < attempts:
                    logger.warning(
                        "LLM returned empty text; retrying attempt %s/%s for model=%s prompt_chars=%s mode=%s",
                        attempt + 1,
                        attempts,
                        self.settings.model_name,
                        prompt_chars,
                        retry_label,
                    )
                    time.sleep(backoff)
            except Exception as exc:
                last_error = exc
                elapsed = time.monotonic() - started_at
                if attempt >= attempts:
                    logger.warning(
                        "LLM request failed after attempt %s/%s for model=%s prompt_chars=%s mode=%s elapsed=%.3fs error=%s",
                        attempt,
                        attempts,
                        self.settings.model_name,
                        prompt_chars,
                        retry_label,
                        elapsed,
                        exc,
                    )
                    raise
                logger.warning(
                    "LLM request failed on attempt %s/%s for model=%s prompt_chars=%s mode=%s elapsed=%.3fs; retrying in %.1fs: %s",
                    attempt,
                    attempts,
                    self.settings.model_name,
                    prompt_chars,
                    retry_label,
                    elapsed,
                    backoff,
                    exc,
                )
                time.sleep(backoff)
        if last_error is not None:
            raise last_error
        return last_text

    def _should_retry_without_thinking(self) -> bool:
        if not self.settings.retry_without_thinking_on_failure:
            return False
        if self.settings.model_type != "OpenAIModel":
            return False
        thinking = str(self.settings.thinking or "").strip().lower()
        return bool(thinking) and thinking != "disabled"

    def _settings_without_thinking(self) -> ModelSettings:
        return replace(
            self.settings,
            thinking="disabled",
            reasoning_effort=None,
            include_reasoning_content=False,
        )

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

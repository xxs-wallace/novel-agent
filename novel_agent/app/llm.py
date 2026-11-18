from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field, replace
from typing import Any, Callable, cast

from .bootstrap import read_api_key
from .utils.json_utils import extract_json_blob


JSON_RETRY_ATTEMPTS = 3
DEFAULT_REQUEST_RETRY_ATTEMPTS = 3
DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS = 1.0
logger = logging.getLogger(__name__)


def _response_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _usage_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict"):
        value = value.dict()
    elif hasattr(value, "__dict__"):
        value = vars(value)
    if not isinstance(value, dict):
        return {}

    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            result[str(key)] = _usage_mapping(item)
        elif item is None or isinstance(item, (bool, int, float, str)):
            result[str(key)] = item
    return result


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
    trust_env: bool = True
    request_retry_attempts: int = DEFAULT_REQUEST_RETRY_ATTEMPTS
    request_retry_backoff_seconds: float = DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS
    retry_without_thinking_on_failure: bool = False
    thinking: str | None = None
    reasoning_effort: str | None = None
    include_reasoning_content: bool = False
    dry_run: bool = False


class InvalidJSONResponseError(ValueError):
    def __init__(
        self,
        *,
        raw_text: str,
        attempts: int,
        finish_reason: str | None = None,
        token_usage: dict[str, Any] | None = None,
        prompt_chars: int = 0,
        system_chars: int = 0,
        user_chars: int = 0,
    ) -> None:
        self.raw_text = raw_text
        self.attempts = attempts
        self.finish_reason = finish_reason
        self.token_usage = dict(token_usage or {})
        self.prompt_chars = prompt_chars
        self.system_chars = system_chars
        self.user_chars = user_chars
        preview = raw_text[:1200]
        super().__init__(
            f"Model did not return valid JSON after {attempts} attempts. "
            f"Raw output preview:\n{preview}"
        )


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    id: str
    name: str
    arguments: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass(frozen=True, slots=True)
class ToolCallModelResponse:
    tool_calls: list[ModelToolCall]
    content: str
    finish_reason: str | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    raw_response: Any | None = None


@dataclass(frozen=True, slots=True)
class TextModelResponse:
    """Text plus provider metadata needed for completion auditing."""

    content: str
    finish_reason: str | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finish_reason": self.finish_reason,
            "token_usage": dict(self.token_usage),
        }


@dataclass(frozen=True, slots=True)
class JsonModelResponse:
    """Parsed JSON plus provider metadata for prompt/output auditing."""

    payload: dict[str, Any] | list[Any]
    raw_text: str
    finish_reason: str | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    prompt_chars: int = 0
    system_chars: int = 0
    user_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "finish_reason": self.finish_reason,
            "token_usage": dict(self.token_usage),
            "prompt_chars": self.prompt_chars,
            "system_chars": self.system_chars,
            "user_chars": self.user_chars,
        }


class JsonModelClient:
    def __init__(self, settings: ModelSettings) -> None:
        self.settings = settings
        if not settings.dry_run and not str(settings.model_name or "").strip():
            raise RuntimeError("ModelSettings.model_name is required for non-dry-run model access")
        self.api_key = read_api_key(
            api_key=settings.api_key,
            api_key_file=settings.api_key_file,
            env_name=settings.api_key_env,
        )
        if not settings.dry_run and settings.model_type == "OpenAIModel" and not str(self.api_key or "").strip():
            raise RuntimeError("OpenAIModel API key is required for non-dry-run model access")
        self.model = None if settings.dry_run else self._build_model()

    def _build_model(self, settings: ModelSettings | None = None):
        settings = settings or self.settings
        if settings.model_type == "OpenAIModel":
            import httpx

            from smolagents.models import OpenAIModel

            thinking = str(settings.thinking or "").strip()
            thinking_disabled = thinking.lower() == "disabled"
            extra_body = {"thinking": {"type": thinking}} if thinking and thinking.lower() != "disabled" else None
            return OpenAIModel(
                model_id=settings.model_name,
                api_base=settings.base_url,
                api_key=self.api_key,
                client_kwargs={
                    "timeout": settings.timeout_seconds,
                    "max_retries": 0,
                    "http_client": httpx.Client(
                        timeout=settings.timeout_seconds,
                        trust_env=settings.trust_env,
                    ),
                },
                temperature=settings.temperature,
                max_tokens=settings.max_output_tokens,
                timeout=settings.timeout_seconds,
                reasoning_effort=None if thinking_disabled else settings.reasoning_effort,
                extra_body=extra_body,
                include_reasoning_content=False if thinking_disabled else settings.include_reasoning_content,
            )
        from smolagents.cli import load_model

        return load_model(
            model_type=settings.model_type,
            model_id=settings.model_name,
            api_base=settings.base_url,
            api_key=self.api_key,
            provider=settings.provider,
        )

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_text: str | None = None,
        timeout_seconds: int | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        include_reasoning_content: bool | None = None,
    ) -> str:
        return self.generate_text_with_metadata(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_text=fallback_text,
            timeout_seconds=timeout_seconds,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            include_reasoning_content=include_reasoning_content,
        ).content

    def generate_text_with_metadata(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_text: str | None = None,
        timeout_seconds: int | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        include_reasoning_content: bool | None = None,
        response_format: dict[str, str] | None = None,
    ) -> TextModelResponse:
        if self.settings.dry_run:
            if fallback_text is None:
                raise RuntimeError("Dry-run mode requires fallback_text")
            return TextModelResponse(content=fallback_text, finish_reason="stop")
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
        request_timeout_seconds = max(1, int(timeout_seconds or self.settings.timeout_seconds or 1))
        active_settings = self._settings_for_call(
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            include_reasoning_content=include_reasoning_content,
        )
        model = self.model if active_settings is self.settings else self._build_model(active_settings)

        try:
            response = self._generate_text_with_retries(
                model=model,
                messages=messages,
                attempts=attempts,
                backoff=backoff,
                prompt_chars=prompt_chars,
                retry_label="primary",
                timeout_seconds=request_timeout_seconds,
                generation_kwargs={"response_format": response_format} if response_format else None,
            )
        except Exception as primary_error:
            if not self._should_retry_without_thinking(active_settings):
                raise
            logger.warning(
                "LLM request exhausted primary attempts for model=%s; retrying with thinking disabled: %s",
                self.settings.model_name,
                primary_error,
            )
            fallback_settings = self._settings_without_thinking(active_settings)
            fallback_model = self._build_model(fallback_settings)
            response = self._generate_text_with_retries(
                model=fallback_model,
                messages=messages,
                attempts=attempts,
                backoff=backoff,
                prompt_chars=prompt_chars,
                retry_label="thinking_disabled",
                timeout_seconds=request_timeout_seconds,
                generation_kwargs={"response_format": response_format} if response_format else None,
            )
        result = self._text_model_response(response)
        if result.content or not self._should_retry_without_thinking(active_settings):
            return result
        logger.warning(
            "LLM returned empty text after primary attempts for model=%s; retrying with thinking disabled",
            self.settings.model_name,
        )
        fallback_settings = self._settings_without_thinking(active_settings)
        fallback_model = self._build_model(fallback_settings)
        response = self._generate_text_with_retries(
            model=fallback_model,
            messages=messages,
            attempts=attempts,
            backoff=backoff,
            prompt_chars=prompt_chars,
            retry_label="thinking_disabled",
            timeout_seconds=request_timeout_seconds,
            generation_kwargs={"response_format": response_format} if response_format else None,
        )
        return self._text_model_response(response)

    def generate_tool_calls(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[Any],
        tool_choice: str | dict[str, Any] | None = "auto",
        timeout_seconds: int | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        include_reasoning_content: bool | None = None,
    ) -> ToolCallModelResponse:
        if self.settings.dry_run:
            raise RuntimeError("Dry-run mode does not support model tool calls")
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
        request_timeout_seconds = max(1, int(timeout_seconds or self.settings.timeout_seconds or 1))
        active_settings = self._settings_for_call(
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            include_reasoning_content=include_reasoning_content,
        )
        model = self.model if active_settings is self.settings else self._build_model(active_settings)
        response = self._generate_tool_call_response_with_retries(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            attempts=attempts,
            backoff=backoff,
            prompt_chars=prompt_chars,
            retry_label="tool_call",
            timeout_seconds=request_timeout_seconds,
        )
        return self._tool_call_model_response(response)

    def _settings_for_call(
        self,
        *,
        thinking: str | None,
        reasoning_effort: str | None,
        include_reasoning_content: bool | None,
    ) -> ModelSettings:
        if thinking is None and reasoning_effort is None and include_reasoning_content is None:
            return self.settings
        next_thinking = self.settings.thinking if thinking is None else thinking
        next_reasoning_effort = self.settings.reasoning_effort if reasoning_effort is None else reasoning_effort
        next_include_reasoning = (
            self.settings.include_reasoning_content
            if include_reasoning_content is None
            else include_reasoning_content
        )
        if str(next_thinking or "").strip().lower() == "disabled":
            next_thinking = None
            next_reasoning_effort = None
            next_include_reasoning = False
        return replace(
            self.settings,
            thinking=next_thinking,
            reasoning_effort=next_reasoning_effort,
            include_reasoning_content=next_include_reasoning,
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
        timeout_seconds: int,
        generation_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started_at = time.monotonic()
            try:
                response = self._generate_with_timeout(
                    model=model,
                    messages=messages,
                    timeout_seconds=timeout_seconds,
                    generation_kwargs={
                        "temperature": self.settings.temperature,
                        **(generation_kwargs or {}),
                    },
                )
                text = str(response.content or "").strip()
                if not text:
                    text = self._extract_text_from_raw_response(response).strip()
                if text:
                    return response
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
        raise RuntimeError(
            f"Model returned empty text after {attempts} attempts for model={self.settings.model_name}"
        )

    def _text_model_response(self, response: Any) -> TextModelResponse:
        content = str(getattr(response, "content", "") or "").strip()
        if not content:
            content = self._extract_text_from_raw_response(response).strip()
        raw = getattr(response, "raw", None)
        choices = _response_field(raw, "choices") or []
        choice = choices[0] if choices else None
        finish_reason = _response_field(choice, "finish_reason")
        usage = _usage_mapping(getattr(response, "token_usage", None))
        raw_usage = _response_field(raw, "usage")
        if raw_usage is not None:
            usage.update(_usage_mapping(raw_usage))
        return TextModelResponse(
            content=content,
            finish_reason=str(finish_reason) if finish_reason is not None else None,
            token_usage=usage,
        )

    def _generate_tool_call_response_with_retries(
        self,
        *,
        model: Any,
        messages: list[Any | dict[str, Any]],
        tools: list[Any],
        tool_choice: str | dict[str, Any] | None,
        attempts: int,
        backoff: float,
        prompt_chars: int,
        retry_label: str,
        timeout_seconds: int,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started_at = time.monotonic()
            try:
                return self._generate_with_timeout(
                    model=model,
                    messages=messages,
                    timeout_seconds=timeout_seconds,
                    generation_kwargs={
                        "temperature": self.settings.temperature,
                        "tools_to_call_from": tools,
                        "tool_choice": tool_choice,
                    },
                )
            except Exception as exc:
                last_error = exc
                elapsed = time.monotonic() - started_at
                if attempt >= attempts:
                    logger.warning(
                        "LLM tool-call request failed after attempt %s/%s for model=%s prompt_chars=%s mode=%s elapsed=%.3fs error=%s",
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
                    "LLM tool-call request failed on attempt %s/%s for model=%s prompt_chars=%s mode=%s elapsed=%.3fs; retrying in %.1f: %s",
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
        raise RuntimeError(f"Model tool-call request failed after {attempts} attempts for model={self.settings.model_name}")

    def _generate_with_timeout(
        self,
        *,
        model: Any,
        messages: list[Any | dict[str, Any]],
        timeout_seconds: int | None = None,
        generation_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        timeout_seconds = max(1, int(timeout_seconds or self.settings.timeout_seconds or 1))
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="novel-agent-llm")
        future = executor.submit(cast(Any, model).generate, messages, **(generation_kwargs or {}))
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(
                f"LLM request timed out after {timeout_seconds}s for model={self.settings.model_name}"
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _should_retry_without_thinking(self, settings: ModelSettings | None = None) -> bool:
        settings = settings or self.settings
        if not self.settings.retry_without_thinking_on_failure:
            return False
        if settings.model_type != "OpenAIModel":
            return False
        thinking = str(settings.thinking or "").strip().lower()
        return bool(thinking) and thinking != "disabled"

    def _settings_without_thinking(self, settings: ModelSettings | None = None) -> ModelSettings:
        settings = settings or self.settings
        return replace(
            settings,
            thinking=None,
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

    def _tool_call_model_response(self, response: Any) -> ToolCallModelResponse:
        content = str(getattr(response, "content", "") or "").strip()
        raw_calls = getattr(response, "tool_calls", None) or []
        calls: list[ModelToolCall] = []
        for index, call in enumerate(raw_calls, start=1):
            call_id = str(getattr(call, "id", "") or f"tool-call-{index}")
            function = getattr(call, "function", None)
            name = str(getattr(function, "name", "") or "")
            arguments = getattr(function, "arguments", {})
            if not name and isinstance(call, dict):
                call_id = str(call.get("id") or call_id)
                function_data = call.get("function") or {}
                if isinstance(function_data, dict):
                    name = str(function_data.get("name") or "")
                    arguments = function_data.get("arguments", {})
            if not name:
                continue
            calls.append(ModelToolCall(id=call_id, name=name, arguments=arguments))
        raw = getattr(response, "raw", None)
        choices = _response_field(raw, "choices") or []
        choice = choices[0] if choices else None
        usage = _usage_mapping(getattr(response, "token_usage", None))
        raw_usage = _response_field(raw, "usage")
        if raw_usage is not None:
            usage.update(_usage_mapping(raw_usage))
        finish_reason = _response_field(choice, "finish_reason")
        return ToolCallModelResponse(
            tool_calls=calls,
            content=content,
            finish_reason=str(finish_reason) if finish_reason is not None else None,
            token_usage=usage,
            raw_response=response,
        )

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory: Callable[[], dict[str, Any] | list[Any]],
        use_fallback_on_error: bool = False,
    ) -> tuple[dict[str, Any] | list[Any], str]:
        response = self.generate_json_with_metadata(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback_factory,
            use_fallback_on_error=use_fallback_on_error,
        )
        return response.payload, response.raw_text

    def generate_json_with_metadata(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory: Callable[[], dict[str, Any] | list[Any]],
        use_fallback_on_error: bool = False,
    ) -> JsonModelResponse:
        if self.settings.dry_run:
            payload = fallback_factory()
            return JsonModelResponse(
                payload=payload,
                raw_text=json.dumps(payload, ensure_ascii=False, indent=2),
                finish_reason="stop",
                prompt_chars=len(system_prompt) + len(user_prompt),
                system_chars=len(system_prompt),
                user_chars=len(user_prompt),
            )
        raw_text = ""
        last_error: ValueError | None = None
        last_response: TextModelResponse | None = None
        for attempt in range(JSON_RETRY_ATTEMPTS):
            last_response = self.generate_text_with_metadata(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format={"type": "json_object"}
                if self.settings.model_type == "OpenAIModel"
                else None,
            )
            raw_text = last_response.content
            try:
                payload = extract_json_blob(raw_text)
                return JsonModelResponse(
                    payload=payload,
                    raw_text=raw_text,
                    finish_reason=last_response.finish_reason,
                    token_usage=dict(last_response.token_usage),
                    prompt_chars=len(system_prompt) + len(user_prompt),
                    system_chars=len(system_prompt),
                    user_chars=len(user_prompt),
                )
            except ValueError as exc:
                last_error = exc
                if attempt < JSON_RETRY_ATTEMPTS - 1:
                    time.sleep(1.0)
                    continue
        if use_fallback_on_error:
            logger.warning(
                "Ignoring generate_json fallback request for model=%s; model failures must surface as errors",
                self.settings.model_name,
            )
        raise InvalidJSONResponseError(
            raw_text=raw_text,
            attempts=JSON_RETRY_ATTEMPTS,
            finish_reason=last_response.finish_reason if last_response else None,
            token_usage=last_response.token_usage if last_response else {},
            prompt_chars=len(system_prompt) + len(user_prompt),
            system_chars=len(system_prompt),
            user_chars=len(user_prompt),
        ) from last_error

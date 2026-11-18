from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .bootstrap import resolve_repo_root
from .services.one_shot_outline_summary_service import OneShotOutlineConfig, OneShotOutlineSummaryService


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(slots=True)
class DirectOpenAICompatibleTextClient:
    model_name: str
    base_url: str
    api_key: str
    temperature: float = 0.2
    max_output_tokens: int = 12000
    timeout_seconds: int = 600
    retry_attempts: int = 2
    retry_backoff_seconds: float = 2.0

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
        import time

        payload: dict[str, object] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        if thinking and thinking.strip().lower() != "disabled":
            payload["thinking"] = {"type": thinking}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        url = self.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        attempts = max(1, int(self.retry_attempts))
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=int(timeout_seconds or self.timeout_seconds),
                ) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                choices = data.get("choices") if isinstance(data, dict) else None
                if not choices:
                    raise RuntimeError(f"model response missing choices: {raw[:1000]}")
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str) and content.strip():
                    return content.strip()
                raise RuntimeError(f"model response missing content: {raw[:1000]}")
            except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                time.sleep(max(0.0, float(self.retry_backoff_seconds)))
        if last_error is not None:
            raise last_error
        raise RuntimeError("model request failed without an error")


def build_model_client() -> DirectOpenAICompatibleTextClient:
    api_key = str(os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for one-shot outline summary")
    return DirectOpenAICompatibleTextClient(
        model_name=os.getenv("NOVEL_AGENT_ONE_SHOT_MODEL_NAME")
        or os.getenv("NOVEL_AGENT_ANALYZER_MODEL_NAME")
        or os.getenv("NOVEL_AGENT_WEB_WRITER_MODEL_NAME")
        or "deepseek-v4-flash",
        base_url=os.getenv("NOVEL_AGENT_ONE_SHOT_BASE_URL")
        or os.getenv("NOVEL_AGENT_ANALYZER_BASE_URL")
        or "https://api.deepseek.com",
        api_key=api_key,
        temperature=float(os.getenv("NOVEL_AGENT_ONE_SHOT_TEMPERATURE", "0.2")),
        max_output_tokens=_env_int("NOVEL_AGENT_ONE_SHOT_MAX_OUTPUT_TOKENS", 12000),
        timeout_seconds=_env_int("NOVEL_AGENT_ONE_SHOT_TIMEOUT_SECONDS", 600),
        retry_attempts=_env_int("NOVEL_AGENT_ONE_SHOT_RETRY_ATTEMPTS", 2),
        retry_backoff_seconds=float(os.getenv("NOVEL_AGENT_ONE_SHOT_RETRY_BACKOFF_SECONDS", "2")),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a read-only one-shot plot outline for a source excerpt.")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-task-id", default="longzu-前三部")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--start-after-line", type=int, default=56706)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--target-min-chars", type=int, default=5000)
    parser.add_argument("--target-max-chars", type=int, default=10000)
    parser.add_argument("--chunk-chars", type=int, default=_env_int("NOVEL_AGENT_ONE_SHOT_CHUNK_CHARS", 36000))
    parser.add_argument("--reference-chars", type=int, default=_env_int("NOVEL_AGENT_ONE_SHOT_REFERENCE_CHARS", 22000))
    parser.add_argument("--character-limit", type=int, default=_env_int("NOVEL_AGENT_ONE_SHOT_CHARACTER_LIMIT", 28))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else repo_root / ".memory" / "one_shot" / str(args.task_id)
    )
    service = OneShotOutlineSummaryService(repo_root=repo_root, model_client=build_model_client())
    result = service.run(
        OneShotOutlineConfig(
            task_id=str(args.task_id),
            base_task_id=str(args.base_task_id),
            source_path=Path(args.source_path),
            start_after_line=int(args.start_after_line),
            output_dir=output_dir,
            target_min_chars=int(args.target_min_chars),
            target_max_chars=int(args.target_max_chars),
            chunk_chars=int(args.chunk_chars),
            reference_chars=int(args.reference_chars),
            character_limit=int(args.character_limit),
        )
    )
    print(f"task_id: {result.task_id}")
    print(f"source_excerpt_path: {result.source_excerpt_path}")
    print(f"outline_path: {result.outline_path}")
    print(f"chunk_count: {result.chunk_count}")
    print(f"outline_chars: {result.outline_chars}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

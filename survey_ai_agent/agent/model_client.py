"""DeepSeek（OpenAI-compatible）模型接入。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from agent.question_analyzer import INSTRUCTIONS, LLMPlan, build_prompt
from config import Settings
from schemas.answer import AnswerItem, Usage
from schemas.question import Question

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

logger = logging.getLogger(__name__)


class LLMError(Exception):
    code = "llm_error"


class LLMConfigurationError(LLMError):
    code = "llm_not_configured"


class LLMUpstreamError(LLMError):
    code = "llm_upstream_error"


@dataclass(slots=True)
class AnalyzeDeps:
    """Agent 工具可访问的只读上下文。"""

    profile: dict[str, Any]
    history: list[AnswerItem]


@dataclass(slots=True)
class LLMResult:
    plan: LLMPlan
    usage: Usage
    model: str


class LLMClient(Protocol):
    async def analyze(
        self,
        *,
        task_id: str,
        page_id: str,
        questions: list[Question],
        profile: dict[str, Any],
        history: list[AnswerItem],
        context: dict[str, Any] | None = None,
    ) -> LLMResult: ...


class DeepSeekLLM:
    """PydanticAI Agent + DeepSeek OpenAI-compatible API。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._agent: Agent[None, LLMPlan] | None = None

    @property
    def configured(self) -> bool:
        return self.settings.deepseek_configured

    def _build_agent(self) -> Agent[None, LLMPlan]:
        if self._agent is None:
            provider = OpenAIProvider(
                base_url=self.settings.deepseek_base_url,
                api_key=self.settings.deepseek_key,
            )
            model = OpenAIChatModel(
                self.settings.deepseek_model,
                provider=provider,
            )
            self._agent = Agent(
                model,
                output_type=LLMPlan,
                deps_type=AnalyzeDeps,
                instructions=INSTRUCTIONS,
                retries=max(1, self.settings.llm_max_retries),
            )

            @self._agent.tool
            def lookup_profile_fact(ctx: RunContext[AnalyzeDeps], key: str) -> str:
                """Look up one value from the respondent profile by key."""
                target = key.strip().lower()
                for profile_key, value in ctx.deps.profile.items():
                    normalized = str(profile_key).strip().lower().replace(" ", "_")
                    if normalized == target or target in normalized:
                        return json.dumps(value, ensure_ascii=False, default=str)
                return "NOT_FOUND"

            @self._agent.tool
            def lookup_history_answer(
                ctx: RunContext[AnalyzeDeps],
                question_id: str,
            ) -> str:
                """Look up a previously confirmed answer for a question."""
                for answer in ctx.deps.history:
                    if answer.question_id == question_id:
                        return json.dumps(
                            answer.model_dump(mode="json"),
                            ensure_ascii=False,
                        )
                return "NOT_FOUND"

        return self._agent

    async def analyze(
        self,
        *,
        task_id: str,
        page_id: str,
        questions: list[Question],
        profile: dict[str, Any],
        history: list[AnswerItem],
        context: dict[str, Any] | None = None,
    ) -> LLMResult:
        if not self.configured:
            raise LLMConfigurationError(
                "未配置 DeepSeek API Key（SURVEY_AI_DEEPSEEK_API_KEY 或 DEEPSEEK_API_KEY）"
            )

        prompt = build_prompt(
            task_id=task_id,
            page_id=page_id,
            questions=questions,
            profile=profile,
            history=history,
            context=context,
        )
        agent = self._build_agent()
        last_error: Exception | None = None
        attempts = max(0, self.settings.llm_max_retries) + 1

        for attempt in range(attempts):
            try:
                async with asyncio.timeout(self.settings.llm_timeout_seconds):
                    result = await agent.run(
                        prompt,
                        deps=AnalyzeDeps(profile=profile, history=history),
                    )
                plan = result.output
                usage = _extract_usage(result.usage, self.settings.deepseek_model)
                return LLMResult(
                    plan=plan,
                    usage=usage,
                    model=self.settings.deepseek_model,
                )
            except TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "DeepSeek 调用超时（第 %d/%d 次，%.1fs）",
                    attempt + 1,
                    attempts,
                    self.settings.llm_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - 需要区分认证错误与可重试错误
                if _is_auth_error(exc):
                    raise LLMConfigurationError(
                        f"DeepSeek 认证失败：{_safe_message(exc)}"
                    ) from exc
                last_error = exc
                logger.warning(
                    "DeepSeek 调用失败（第 %d/%d 次）：%s",
                    attempt + 1,
                    attempts,
                    _safe_message(exc),
                )

            if attempt + 1 < attempts:
                await asyncio.sleep(min(2 ** attempt, 8))

        raise LLMUpstreamError(
            f"DeepSeek 调用失败：{_safe_message(last_error) if last_error else '未知错误'}"
        ) from last_error


def _extract_usage(usage: Any, model: str) -> Usage:
    prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    total_tokens = int(
        getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
    )
    return Usage(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _is_auth_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return True
    try:
        import openai  # type: ignore

        if isinstance(
            exc,
            (openai.AuthenticationError, openai.PermissionDeniedError),
        ):
            return True
    except Exception:  # pragma: no cover - openai 不可用时忽略
        pass
    message = _safe_message(exc).lower()
    return any(
        marker in message
        for marker in ("authentication", "invalid api key", "unauthorized", "401", "403")
    )


def _safe_message(exc: Exception | None) -> str:
    if exc is None:
        return "未知错误"
    message = str(exc).strip().replace("\n", " ")
    return message[:500]

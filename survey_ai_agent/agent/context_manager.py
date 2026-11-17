"""任务上下文：受访者资料、已确认答案与页面哈希。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from schemas.answer import AnswerItem, AnswerStatus
from schemas.question import Question
from storage.base import SurveyStore


class ContextManager:
    def __init__(self, store: SurveyStore) -> None:
        self.store = store

    async def load(self, task_id: str) -> dict[str, Any]:
        return await self.store.get_context(task_id) or {}

    async def save(
        self,
        *,
        task_id: str,
        profile: dict[str, Any],
        answers: list[AnswerItem],
        questions: list[Question],
        page_id: str,
        html_sha256: str,
    ) -> dict[str, Any]:
        context = await self.load(task_id)
        now = datetime.now(timezone.utc).isoformat()

        context["profile"] = profile
        context["updated_at"] = now

        pages = context.setdefault("pages", {})
        pages[page_id] = {"html_sha256": html_sha256, "updated_at": now}

        fingerprint_by_id = {
            question.question_id: question.fingerprint for question in questions
        }
        confirmed = context.setdefault("confirmed_answers", {})
        for answer in answers:
            if answer.status != AnswerStatus.ready:
                continue
            key = fingerprint_by_id.get(answer.question_id) or answer.question_id
            confirmed[key] = answer.model_dump(mode="json")

        await self.store.save_context(task_id, context)
        return context


def profile_changed(
    previous_context: dict[str, Any],
    current_profile: dict[str, Any],
) -> bool:
    previous = previous_context.get("profile")
    if previous is None:
        return True
    return _canonical(previous) != _canonical(current_profile)


def _canonical(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

"""内存存储：测试、无数据库环境与本地演示使用。"""

from __future__ import annotations

import copy
from typing import Any


class MemoryStore:
    def __init__(self) -> None:
        self.contexts: dict[str, dict[str, Any]] = {}
        self.pages: dict[tuple[str, str], dict[str, Any]] = {}
        self.answers: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.usages: list[dict[str, Any]] = []
        self.profiles: dict[int, dict[str, Any]] = {}
        self._sequence = 0

    async def init(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def get_context(self, task_id: str) -> dict[str, Any] | None:
        value = self.contexts.get(task_id)
        return copy.deepcopy(value) if value is not None else None

    async def save_context(self, task_id: str, context: dict[str, Any]) -> None:
        self.contexts[task_id] = copy.deepcopy(context)

    async def get_answers(self, task_id: str) -> list[dict[str, Any]]:
        rows = [
            copy.deepcopy(row)
            for (row_task, _, _), row in self.answers.items()
            if row_task == task_id
        ]
        rows.sort(key=lambda row: row.get("_sequence", 0), reverse=True)
        return rows

    async def save_page(
        self,
        *,
        task_id: str,
        page_id: str,
        html_sha256: str,
        questions_json: list[dict[str, Any]],
        plan_json: dict[str, Any],
        page_status: str,
    ) -> None:
        self.pages[(task_id, page_id)] = {
            "task_id": task_id,
            "page_id": page_id,
            "html_sha256": html_sha256,
            "questions_json": copy.deepcopy(questions_json),
            "plan_json": copy.deepcopy(plan_json),
            "page_status": page_status,
        }

    async def save_answers(
        self,
        *,
        task_id: str,
        page_id: str,
        rows: list[dict[str, Any]],
    ) -> None:
        for key in [
            key for key in self.answers if key[0] == task_id and key[1] == page_id
        ]:
            del self.answers[key]
        for row in rows:
            self._sequence += 1
            stored = copy.deepcopy(row)
            stored["_sequence"] = self._sequence
            self.answers[(task_id, page_id, row["question_id"])] = stored

    async def record_usage(
        self,
        *,
        task_id: str,
        page_id: str,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        self.usages.append(
            {
                "task_id": task_id,
                "page_id": page_id,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
        )

    async def load_profile(self, respondent_id: int) -> dict[str, Any] | None:
        return copy.deepcopy(self.profiles.get(respondent_id))

    def seed_profile(self, respondent_id: int, profile: dict[str, Any]) -> None:
        self.profiles[respondent_id] = copy.deepcopy(profile)

"""存储接口定义。"""

from __future__ import annotations

from typing import Any, Protocol


class StoreError(Exception):
    code = "store_unavailable"


class SurveyStore(Protocol):
    async def init(self) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...

    async def get_context(self, task_id: str) -> dict[str, Any] | None: ...

    async def save_context(self, task_id: str, context: dict[str, Any]) -> None: ...

    async def get_answers(self, task_id: str) -> list[dict[str, Any]]: ...

    async def save_page(
        self,
        *,
        task_id: str,
        page_id: str,
        html_sha256: str,
        questions_json: list[dict[str, Any]],
        plan_json: dict[str, Any],
        page_status: str,
    ) -> None: ...

    async def save_answers(
        self,
        *,
        task_id: str,
        page_id: str,
        rows: list[dict[str, Any]],
    ) -> None: ...

    async def record_usage(
        self,
        *,
        task_id: str,
        page_id: str,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None: ...

    async def load_profile(self, respondent_id: int) -> dict[str, Any] | None: ...

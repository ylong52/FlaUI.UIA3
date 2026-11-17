from __future__ import annotations

import os
import uuid

import pytest

from config import Settings
from storage.mysql_store import MySQLStore

pytestmark = pytest.mark.skipif(
    os.getenv("SURVEY_AI_TEST_MYSQL") != "1",
    reason="设置 SURVEY_AI_TEST_MYSQL=1 才会执行真实 MySQL 集成测试",
)


async def test_mysql_roundtrip() -> None:
    settings = Settings()
    store = MySQLStore(settings)
    await store.init()

    assert await store.ping() is True

    task_id = f"it-{uuid.uuid4().hex[:12]}"
    await store.save_context(task_id, {"profile": {"age": 29}})
    assert (await store.get_context(task_id))["profile"]["age"] == 29

    await store.save_page(
        task_id=task_id,
        page_id="p1",
        html_sha256="a" * 64,
        questions_json=[{"question_id": "Q1"}],
        plan_json={"status": "complete"},
        page_status="complete",
    )

    await store.save_answers(
        task_id=task_id,
        page_id="p1",
        rows=[
            {
                "question_id": "Q1",
                "fingerprint": "f" * 64,
                "question_type": "single_choice",
                "selected_options": ["a"],
                "answer_text": None,
                "matrix_selections": {},
                "ranking": [],
                "numeric_value": None,
                "status": "ready",
                "source": "respondent_profile",
                "confidence": None,
                "notes": None,
            }
        ],
    )

    rows = await store.get_answers(task_id)
    assert len(rows) == 1
    assert rows[0]["selected_options"] == ["a"]

    await store.record_usage(
        task_id=task_id,
        page_id="p1",
        model="fake",
        prompt_tokens=1,
        completion_tokens=2,
        total_tokens=3,
    )
    await store.close()

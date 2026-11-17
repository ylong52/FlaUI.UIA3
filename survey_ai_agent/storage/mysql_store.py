"""MySQL / MariaDB 存储实现。

复用 survey_bg_manage 同一个数据库，表名以 ai_agent_* 前缀隔离。
所有同步 PyMySQL 调用通过 asyncio.to_thread 执行，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import Settings
from storage.base import StoreError

logger = logging.getLogger(__name__)


class MySQLStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

    # ------------------------------------------------------------ lifecycle

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for statement in _split_statements(self._schema):
                    cursor.execute(statement)
        finally:
            connection.close()

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self._ping_sync)
            return True
        except StoreError:
            return False

    def _ping_sync(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
        finally:
            connection.close()

    async def close(self) -> None:
        return None

    # ------------------------------------------------------------ context

    async def get_context(self, task_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_context_sync, task_id)

    def _get_context_sync(self, task_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT context_json FROM ai_agent_context WHERE task_id = %s",
                    (task_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return _json_load(row.get("context_json")) or {}

    async def save_context(self, task_id: str, context: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save_context_sync, task_id, context)

    def _save_context_sync(self, task_id: str, context: dict[str, Any]) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_agent_context (task_id, context_json)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE context_json = VALUES(context_json)
                    """,
                    (task_id, _json_dump(context)),
                )
        finally:
            connection.close()

    # ------------------------------------------------------------ answers

    async def get_answers(self, task_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_answers_sync, task_id)

    def _get_answers_sync(self, task_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT task_id, page_id, question_id, fingerprint, question_type,
                           selected_options_json, answer_text, matrix_json, ranking_json,
                           numeric_value, status, source, confidence, notes
                    FROM ai_agent_answers
                    WHERE task_id = %s
                    ORDER BY updated_at DESC, id DESC
                    """,
                    (task_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "task_id": row["task_id"],
                    "page_id": row["page_id"],
                    "question_id": row["question_id"],
                    "fingerprint": row.get("fingerprint") or "",
                    "question_type": row["question_type"],
                    "selected_options": _json_load(row.get("selected_options_json")) or [],
                    "answer_text": row.get("answer_text"),
                    "matrix_selections": _json_load(row.get("matrix_json")) or {},
                    "ranking": _json_load(row.get("ranking_json")) or [],
                    "numeric_value": float(row["numeric_value"])
                    if row.get("numeric_value") is not None
                    else None,
                    "status": row["status"],
                    "source": row.get("source"),
                    "confidence": float(row["confidence"])
                    if row.get("confidence") is not None
                    else None,
                    "notes": row.get("notes"),
                }
            )
        return result

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
        await asyncio.to_thread(
            self._save_page_sync,
            task_id,
            page_id,
            html_sha256,
            questions_json,
            plan_json,
            page_status,
        )

    def _save_page_sync(
        self,
        task_id: str,
        page_id: str,
        html_sha256: str,
        questions_json: list[dict[str, Any]],
        plan_json: dict[str, Any],
        page_status: str,
    ) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_agent_pages
                        (task_id, page_id, html_sha256, questions_json, plan_json, page_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        html_sha256 = VALUES(html_sha256),
                        questions_json = VALUES(questions_json),
                        plan_json = VALUES(plan_json),
                        page_status = VALUES(page_status)
                    """,
                    (
                        task_id,
                        page_id,
                        html_sha256,
                        _json_dump(questions_json),
                        _json_dump(plan_json),
                        page_status,
                    ),
                )
        finally:
            connection.close()

    async def save_answers(
        self,
        *,
        task_id: str,
        page_id: str,
        rows: list[dict[str, Any]],
    ) -> None:
        await asyncio.to_thread(self._save_answers_sync, task_id, page_id, rows)

    def _save_answers_sync(
        self,
        task_id: str,
        page_id: str,
        rows: list[dict[str, Any]],
    ) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM ai_agent_answers WHERE task_id = %s AND page_id = %s",
                    (task_id, page_id),
                )
                for row in rows:
                    cursor.execute(
                        """
                        INSERT INTO ai_agent_answers
                            (task_id, page_id, question_id, fingerprint, question_type,
                             selected_options_json, answer_text, matrix_json, ranking_json,
                             numeric_value, status, source, confidence, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            task_id,
                            page_id,
                            row["question_id"],
                            row.get("fingerprint") or "",
                            row["question_type"],
                            _json_dump(row.get("selected_options") or []),
                            row.get("answer_text"),
                            _json_dump(row.get("matrix_selections") or {}),
                            _json_dump(row.get("ranking") or []),
                            row.get("numeric_value"),
                            row["status"],
                            row.get("source"),
                            row.get("confidence"),
                            row.get("notes"),
                        ),
                    )
        finally:
            connection.close()

    # ------------------------------------------------------------ usage

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
        await asyncio.to_thread(
            self._record_usage_sync,
            task_id,
            page_id,
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )

    def _record_usage_sync(
        self,
        task_id: str,
        page_id: str,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_agent_llm_usage
                        (task_id, page_id, model, prompt_tokens, completion_tokens, total_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        task_id,
                        page_id,
                        model,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                    ),
                )
        finally:
            connection.close()

    # ------------------------------------------------------------ profiles

    async def load_profile(self, respondent_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._load_profile_sync, respondent_id)

    def _load_profile_sync(self, respondent_id: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, name, age, birthday, gender, country, zip,
                           threat_score, threat_level
                    FROM inv_respondent_profiles
                    WHERE id = %s
                    """,
                    (respondent_id,),
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "respondent_id": row["id"],
                        "user_id": row.get("user_id"),
                        "name": row.get("name") or None,
                        "age": row.get("age"),
                        "birthday": str(row["birthday"]) if row.get("birthday") else None,
                        "gender": row.get("gender") or None,
                        "country": row.get("country") or None,
                        "zip": row.get("zip") or None,
                        "threat_score": row.get("threat_score"),
                        "threat_level": row.get("threat_level"),
                        "_source": "inv_respondent_profiles",
                    }

                cursor.execute(
                    """
                    SELECT id, user_id, age, gender, country, city, subdivision
                    FROM survey_responses
                    WHERE id = %s
                    """,
                    (respondent_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                gender_value = row.get("gender")
                return {
                    "respondent_id": row["id"],
                    "user_id": row.get("user_id"),
                    "age": row.get("age"),
                    "gender": {1: "male", 2: "female"}.get(gender_value),
                    "country": row.get("country") or None,
                    "city": row.get("city") or None,
                    "state": row.get("subdivision") or None,
                    "_source": "survey_responses",
                }
        except pymysql.MySQLError as exc:
            if exc.args and exc.args[0] == 1146:  # 业务表不存在时忽略
                logger.warning("受访者资料表不存在：%s", exc)
                return None
            raise StoreError(f"读取受访者资料失败：{exc}") from exc
        finally:
            connection.close()

    # ------------------------------------------------------------ internals

    def _connect(self) -> pymysql.connections.Connection:
        try:
            return pymysql.connect(
                host=self.settings.db_host,
                port=self.settings.db_port,
                user=self.settings.db_user,
                password=self.settings.db_password.get_secret_value(),
                database=self.settings.db_name,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=True,
                connect_timeout=5,
                read_timeout=30,
                write_timeout=30,
            )
        except pymysql.MySQLError as exc:
            raise StoreError(f"MySQL 连接失败：{exc}") from exc


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _split_statements(script: str) -> list[str]:
    lines = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(line)
    script = "\n".join(lines)
    return [statement.strip() for statement in script.split(";") if statement.strip()]

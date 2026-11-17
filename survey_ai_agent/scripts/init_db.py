"""初始化 ai_agent_* 表（同库 survey_bg_manage）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Settings  # noqa: E402
from storage.mysql_store import MySQLStore  # noqa: E402


async def main() -> int:
    settings = Settings()
    print(
        f"连接 MySQL {settings.db_user}@{settings.db_host}:{settings.db_port}"
        f"/{settings.db_name} ..."
    )
    store = MySQLStore(settings)
    await store.init()
    ok = await store.ping()
    print("数据库连接：", "OK" if ok else "FAILED")
    print("已确保表：ai_agent_tasks, ai_agent_pages, ai_agent_answers, "
          "ai_agent_context, ai_agent_llm_usage")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

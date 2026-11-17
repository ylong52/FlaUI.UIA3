"""POST /api/v1/agent/analyze 请求结构。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schemas.answer import AnswerItem


class AnalyzeOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reuse_previous: bool = True
    include_questions: bool = True
    max_questions: int = 500
    # auto: 自动识别已知测试页；survey_test: 强制使用测试页适配器；html: 只用通用 HTML 解析
    page_adapter: str = "auto"


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(min_length=1, max_length=128)
    page_id: str = Field(min_length=1, max_length=128)
    html: str = Field(min_length=1)
    respondent_profile: dict[str, Any] = Field(default_factory=dict)
    answer_history: list[AnswerItem] = Field(default_factory=list)

    # 可选：从同一个 survey_bg_manage 库读取受访者资料（inv_respondent_profiles / survey_responses）。
    respondent_id: int | None = None
    survey_id: str | None = None

    options: AnalyzeOptions = Field(default_factory=AnalyzeOptions)

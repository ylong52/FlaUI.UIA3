"""答案计划与接口响应的数据结构。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from schemas.question import Question, QuestionType


class AnswerStatus(StrEnum):
    ready = "ready"
    needs_review = "needs_review"
    skipped = "skipped"
    invalid = "invalid"


class AnswerSource(StrEnum):
    respondent_profile = "respondent_profile"
    history = "history"
    llm = "llm_inference"
    rule = "rule"
    manual = "manual"


class AnswerItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str
    question_type: QuestionType
    selected_options: list[str] = Field(default_factory=list)
    answer_text: str | None = None
    matrix_selections: dict[str, str] = Field(default_factory=dict)
    ranking: list[str] = Field(default_factory=list)
    numeric_value: float | None = None
    status: AnswerStatus
    source: AnswerSource | None = None
    confidence: float | None = None
    notes: str | None = None


class Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class PageStatus(StrEnum):
    complete = "complete"
    partial = "partial"
    error = "error"


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str
    page_id: str
    status: PageStatus
    answers: list[AnswerItem]
    questions: list[Question] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    warnings: list[str] = Field(default_factory=list)

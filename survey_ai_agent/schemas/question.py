"""题目与选项的数据结构。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuestionType(StrEnum):
    single_choice = "single_choice"
    multi_choice = "multi_choice"
    text = "text"
    number = "number"
    dropdown = "dropdown"
    matrix = "matrix"
    rating = "rating"
    ranking = "ranking"
    unknown = "unknown"


class Option(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = ""
    value: str | None = None
    disabled: bool = False
    exclusive: bool = False


class MatrixRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = ""


class MatrixSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rows: list[MatrixRow] = Field(default_factory=list)
    columns: list[Option] = Field(default_factory=list)


class NumericSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    min: float | None = None
    max: float | None = None
    step: float | None = None


class Question(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str
    text: str = ""
    question_type: QuestionType = QuestionType.unknown
    required: bool = False
    options: list[Option] = Field(default_factory=list)
    matrix: MatrixSpec | None = None
    numeric: NumericSpec | None = None
    min_selections: int | None = None
    max_selections: int | None = None
    depends_on: str | None = None
    depends_value: Any | None = None
    conditional_hint: str | None = None
    requires_personal_fact: bool = False
    text_unavailable: bool = False
    options_unresolved: bool = False
    inferred_topic: str | None = None
    hidden: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""

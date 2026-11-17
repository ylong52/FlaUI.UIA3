"""LLM 任务指令、结构化输出模型与提示词构造。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from schemas.answer import AnswerItem
from schemas.question import Question


class LLMAnswer(BaseModel):
    question_id: str
    selected_options: list[str] = Field(default_factory=list)
    answer_text: str | None = None
    matrix_selections: dict[str, str] = Field(default_factory=dict)
    ranking: list[str] = Field(default_factory=list)
    numeric_value: float | None = None
    status: Literal["ready", "needs_review", "skipped"] = "ready"
    confidence: float | None = None
    notes: str | None = None


class LLMQuestionNote(BaseModel):
    question_id: str
    requires_personal_fact: bool | None = None
    notes: str | None = None


class LLMPlan(BaseModel):
    answers: list[LLMAnswer] = Field(default_factory=list)
    notes: list[LLMQuestionNote] = Field(default_factory=list)


INSTRUCTIONS = """\
You are a meticulous survey-answering engine.

Your job: read the structured survey questions, the respondent profile, and confirmed
answer history, then produce a complete machine-executable answer plan.

Hard rules:
1. VERIFIABLE PERSONAL FACTS are only: demographics (age, country, gender, ethnicity,
   income, education, household/children, marital status), employment/company/industry
   details, contact details, and actual purchase / product / brand usage or experience.
   These may ONLY come from `respondent_profile` or `confirmed_history`.
   Never invent them. If a required one is missing, return status="needs_review" with
   empty answer fields.
2. OPINION / PREFERENCE / OPEN-ENDED questions may be answered with a reasonable,
   natural response even when the profile is empty. This includes questions like
   "Name three things you could not live without", "Describe how to make good coffee",
   "Rank these factors", "Rate importance", "Which option would you choose", and
   "What factor matters most to your company". Do NOT return needs_review merely
   because an opinion is not listed in the profile.
   Never fabricate specific past purchases or brand-usage history, but general
   preferences and opinions are allowed.
3. Use ONLY option IDs that appear in the corresponding question's `options` (or matrix
   rows/columns). Never output an option that is not on the page.
4. single_choice / dropdown: exactly one selected option.
5. multi_choice: respect min_selections / max_selections. Never combine an exclusive
   option (e.g. "None of the above", "N/A") with other options.
6. text: answer in 1-3 natural, concise English sentences; no repetitive boilerplate.
7. number / rating: put the value in numeric_value and respect numeric.min / max.
8. matrix: matrix_selections MUST contain EVERY row id exactly once, each mapped to one
   valid column id. Do not omit rows.
9. ranking: ranking MUST contain every option ID exactly once, in preferred order.
10. If a question is conditional and its dependency is not satisfied, return
    status="skipped" with empty fields.
11. If question text was unavailable (image-only) but options make the topic clear,
    infer carefully from the options; otherwise needs_review.
12. Return one answer for every question listed. Do not omit questions.
13. Do not include explanations outside the structured output.

Output the answers in the exact JSON structure required by the response schema.
"""


def build_prompt(
    *,
    task_id: str,
    page_id: str,
    questions: list[Question],
    profile: dict[str, Any],
    history: list[AnswerItem],
    context: dict[str, Any] | None = None,
) -> str:
    payload = {
        "task_id": task_id,
        "page_id": page_id,
        "respondent_profile": profile or {},
        "confirmed_history": [
            answer.model_dump(mode="json") for answer in history[-100:]
        ],
        "context": context or {},
        "questions": [_question_payload(question) for question in questions],
    }
    return (
        "Analyze the following survey page and return the complete answer plan.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _question_payload(question: Question) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question_id": question.question_id,
        "type": question.question_type.value,
        "text": question.text or None,
        "required": question.required,
        "options": [
            {"id": option.id, "label": option.label}
            for option in question.options
        ],
        "min_selections": question.min_selections,
        "max_selections": question.max_selections,
        "depends_on": question.depends_on,
        "requires_personal_fact": question.requires_personal_fact,
        "text_unavailable": question.text_unavailable,
        "inferred_topic": question.inferred_topic,
    }
    if question.matrix is not None:
        payload["matrix"] = {
            "rows": [
                {"id": row.id, "label": row.label}
                for row in question.matrix.rows
            ],
            "columns": [
                {"id": column.id, "label": column.label}
                for column in question.matrix.columns
            ],
        }
    if question.numeric is not None:
        payload["numeric"] = question.numeric.model_dump()
    return payload


def apply_notes(questions: list[Question], notes: list[LLMQuestionNote]) -> list[Question]:
    """应用 LLM 对题目的补充判断；只会把题目标记为“更需要人工确认”。"""
    by_id = {note.question_id: note for note in notes}
    result: list[Question] = []
    for question in questions:
        note = by_id.get(question.question_id)
        if note is not None and note.requires_personal_fact is True:
            question = question.model_copy(
                update={"requires_personal_fact": True}
            )
        result.append(question)
    return result

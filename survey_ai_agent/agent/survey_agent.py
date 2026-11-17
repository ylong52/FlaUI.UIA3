"""问卷分析主流程：提取 → 复用 → 生成 → 校验 → 持久化。"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from agent.answer_engine import RuleAnswerEngine
from agent.answer_validator import validate_plan
from agent.context_manager import ContextManager, profile_changed
from agent.model_client import DeepSeekLLM, LLMClient, LLMConfigurationError
from agent.question_analyzer import LLMAnswer, apply_notes
from config import Settings
from parser.question_extractor import extract_questions
from parser.survey_test_adapter import build_survey_test_questions
from schemas.answer import (
    AnalyzeResponse,
    AnswerItem,
    AnswerSource,
    AnswerStatus,
    PageStatus,
    Usage,
)
from schemas.question import Question, QuestionType
from schemas.request import AnalyzeRequest
from storage.base import SurveyStore

logger = logging.getLogger(__name__)


class NoQuestionsError(Exception):
    code = "no_questions"


class SurveyAnalyzer:
    def __init__(
        self,
        settings: Settings,
        store: SurveyStore,
        llm: LLMClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.rule_engine = RuleAnswerEngine()
        self.context_manager = ContextManager(store)

        self.llm = llm
        if self.llm is None and settings.effective_llm_mode == "deepseek":
            self.llm = DeepSeekLLM(settings)

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        questions = None
        if request.options.page_adapter in {"auto", "survey_test"}:
            questions = build_survey_test_questions(request.html)
        if not questions:
            questions = extract_questions(
                request.html,
                max_questions=request.options.max_questions,
            )
        if not questions:
            raise NoQuestionsError("未能从 HTML 中识别出任何题目")

        profile = await self._resolve_profile(request)
        stored_rows = await self.store.get_answers(request.task_id)
        stored_answers = [_row_to_answer(row) for row in stored_rows]
        history = stored_answers + list(request.answer_history)
        context = await self.context_manager.load(request.task_id)

        reused, pending = _reuse_answers(
            questions=questions,
            rows=stored_rows,
            context=context,
            profile=profile,
            enabled=request.options.reuse_previous,
        )

        warnings: list[str] = []
        notes = []
        usage = Usage(model=None)

        if pending:
            usage, new_answers, notes, llm_used, generate_warnings = await self._generate(
                request=request,
                questions=pending,
                profile=profile,
                history=history + reused,
                context=context,
            )
            warnings.extend(generate_warnings)
            if llm_used:
                logger.info(
                    "DeepSeek 已分析 task=%s page=%s questions=%d tokens=%d",
                    request.task_id,
                    request.page_id,
                    len(pending),
                    usage.total_tokens,
                )
        else:
            new_answers = []
            warnings.append("本页全部题目复用了已验证的答案，未调用模型")

        if notes:
            questions = apply_notes(questions, notes)

        answers = reused + new_answers
        validated, validation_warnings = validate_plan(
            answers,
            questions,
            profile,
            history + reused,
        )
        warnings.extend(validation_warnings)

        status = _page_status(validated, questions)
        if status == PageStatus.partial:
            unresolved = [
                answer.question_id
                for answer in validated
                if answer.status in {AnswerStatus.needs_review, AnswerStatus.invalid}
            ]
            if unresolved:
                warnings.append(f"需要人工确认的题目：{', '.join(unresolved)}")

        html_sha256 = hashlib.sha256(request.html.encode("utf-8")).hexdigest()
        response_questions = questions if request.options.include_questions else []

        response = AnalyzeResponse(
            task_id=request.task_id,
            page_id=request.page_id,
            status=status,
            answers=validated,
            questions=response_questions,
            usage=usage,
            warnings=_dedupe(warnings),
        )

        # 持久化：页面计划、逐题答案、上下文、token 统计。
        await self.store.save_page(
            task_id=request.task_id,
            page_id=request.page_id,
            html_sha256=html_sha256,
            questions_json=[
                question.model_dump(mode="json") for question in questions
            ],
            plan_json=response.model_dump(mode="json"),
            page_status=status.value,
        )
        await self.store.save_answers(
            task_id=request.task_id,
            page_id=request.page_id,
            rows=[
                _answer_to_row(answer, questions) for answer in validated
            ],
        )
        await self.context_manager.save(
            task_id=request.task_id,
            profile=profile,
            answers=validated,
            questions=questions,
            page_id=request.page_id,
            html_sha256=html_sha256,
        )
        if usage.total_tokens or usage.model not in {None, "rule", "reuse"}:
            await self.store.record_usage(
                task_id=request.task_id,
                page_id=request.page_id,
                model=usage.model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )

        return response

    async def _generate(
        self,
        *,
        request: AnalyzeRequest,
        questions: list[Question],
        profile: dict[str, Any],
        history: list[AnswerItem],
        context: dict[str, Any],
    ) -> tuple[Usage, list[AnswerItem], list, bool, list[str]]:
        warnings: list[str] = []

        # 先用确定性规则回答可由真实资料确定的题目；这些答案不交给模型，
        # 从源头避免把模型推测当成个人事实。
        rule_answers = self.rule_engine.answer(questions, profile, history)
        if self.llm is None:
            return (
                Usage(model="rule"),
                rule_answers,
                [],
                False,
                ["mock 模式：仅使用受访者资料与历史答案，不生成主观内容"],
            )

        fact_answers = [
            answer for answer in rule_answers if answer.status == AnswerStatus.ready
        ]
        llm_questions = [
            question
            for question, answer in zip(questions, rule_answers)
            if answer.status != AnswerStatus.ready
        ]

        if not llm_questions:
            return (
                Usage(model="rule"),
                fact_answers,
                [],
                False,
                ["可确定的题目已由资料/规则完成，本次未调用模型"],
            )

        if isinstance(self.llm, DeepSeekLLM) and not self.llm.configured:
            raise LLMConfigurationError(
                "未配置 DeepSeek API Key（SURVEY_AI_DEEPSEEK_API_KEY 或 DEEPSEEK_API_KEY）"
            )

        result = await self.llm.analyze(
            task_id=request.task_id,
            page_id=request.page_id,
            questions=llm_questions,
            profile=profile,
            history=history + fact_answers,
            context=context,
        )
        by_id = {question.question_id: question for question in llm_questions}
        llm_answers: list[AnswerItem] = []
        for llm_answer in result.plan.answers:
            question = by_id.get(llm_answer.question_id)
            if question is None:
                continue
            llm_answers.append(_llm_answer_to_item(llm_answer, question))
        return (
            result.usage,
            fact_answers + llm_answers,
            result.plan.notes,
            True,
            warnings,
        )

    async def _resolve_profile(self, request: AnalyzeRequest) -> dict[str, Any]:
        profile = dict(request.respondent_profile or {})
        if request.respondent_id is not None:
            stored = await self.store.load_profile(request.respondent_id)
            if stored:
                merged = dict(stored)
                merged.update(profile)  # 请求中的资料优先
                profile = merged
        return profile


# ---------------------------------------------------------------- reuse


def _reuse_answers(
    *,
    questions: list[Question],
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    profile: dict[str, Any],
    enabled: bool,
) -> tuple[list[AnswerItem], list[Question]]:
    if not enabled:
        return [], list(questions)

    by_fingerprint: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("status") != AnswerStatus.ready.value:
            continue
        fingerprint = row.get("fingerprint") or ""
        if fingerprint and fingerprint not in by_fingerprint:
            by_fingerprint[fingerprint] = row

    changed = profile_changed(context, profile)
    reused: list[AnswerItem] = []
    pending: list[Question] = []

    for question in questions:
        row = by_fingerprint.get(question.fingerprint)
        if row is None:
            pending.append(question)
            continue
        if changed and question.requires_personal_fact:
            pending.append(question)
            continue

        answer = _row_to_answer(row)
        if not _answer_still_valid(answer, question):
            pending.append(question)
            continue

        reused.append(
            answer.model_copy(
                update={
                    "question_type": question.question_type,
                    "source": AnswerSource.history,
                    "notes": "复用未变化且已验证的答案",
                }
            )
        )

    return reused, pending


def _answer_still_valid(answer: AnswerItem, question: Question) -> bool:
    if answer.status != AnswerStatus.ready:
        return False
    option_ids = {option.id for option in question.options}
    if question.question_type in {
        QuestionType.single_choice,
        QuestionType.multi_choice,
        QuestionType.dropdown,
    } and not answer.selected_options:
        # 选择题没有勾选项时不能复用（防止空答案被标成 ready 后扩散）。
        return False
    if answer.selected_options and not set(answer.selected_options) <= option_ids:
        return False
    if question.matrix is not None:
        row_ids = {row.id for row in question.matrix.rows}
        column_ids = {column.id for column in question.matrix.columns}
        if not set(answer.matrix_selections) <= row_ids:
            return False
        if not set(answer.matrix_selections.values()) <= column_ids:
            return False
    if answer.ranking and set(answer.ranking) != option_ids:
        return False
    return True


# ---------------------------------------------------------------- conversion


def _llm_answer_to_item(answer: LLMAnswer, question: Question) -> AnswerItem:
    status = AnswerStatus(answer.status)
    if status != AnswerStatus.ready:
        return AnswerItem(
            question_id=answer.question_id,
            question_type=question.question_type,
            status=status,
            notes=answer.notes,
        )
    return AnswerItem(
        question_id=answer.question_id,
        question_type=question.question_type,
        selected_options=answer.selected_options,
        answer_text=answer.answer_text,
        matrix_selections=answer.matrix_selections,
        ranking=answer.ranking,
        numeric_value=answer.numeric_value,
        status=status,
        source=AnswerSource.llm,
        confidence=answer.confidence,
        notes=answer.notes,
    )


def _row_to_answer(row: dict[str, Any]) -> AnswerItem:
    try:
        question_type = QuestionType(row.get("question_type") or "unknown")
    except ValueError:
        question_type = QuestionType.unknown
    try:
        status = AnswerStatus(row.get("status") or "needs_review")
    except ValueError:
        status = AnswerStatus.needs_review
    source = None
    if row.get("source"):
        try:
            source = AnswerSource(row["source"])
        except ValueError:
            source = None
    return AnswerItem(
        question_id=row["question_id"],
        question_type=question_type,
        selected_options=list(row.get("selected_options") or []),
        answer_text=row.get("answer_text"),
        matrix_selections=dict(row.get("matrix_selections") or {}),
        ranking=list(row.get("ranking") or []),
        numeric_value=row.get("numeric_value"),
        status=status,
        source=source,
        confidence=row.get("confidence"),
        notes=row.get("notes"),
    )


def _answer_to_row(answer: AnswerItem, questions: list[Question]) -> dict[str, Any]:
    fingerprint_by_id = {
        question.question_id: question.fingerprint for question in questions
    }
    return {
        "question_id": answer.question_id,
        "fingerprint": fingerprint_by_id.get(answer.question_id, ""),
        "question_type": answer.question_type.value,
        "selected_options": answer.selected_options,
        "answer_text": answer.answer_text,
        "matrix_selections": answer.matrix_selections,
        "ranking": answer.ranking,
        "numeric_value": answer.numeric_value,
        "status": answer.status.value,
        "source": answer.source.value if answer.source else None,
        "confidence": answer.confidence,
        "notes": answer.notes,
    }


# ---------------------------------------------------------------- status


def _page_status(
    answers: list[AnswerItem],
    questions: list[Question],
) -> PageStatus:
    by_id = {answer.question_id: answer for answer in answers}
    for question in questions:
        answer = by_id.get(question.question_id)
        if answer is None:
            return PageStatus.partial
        if answer.status in {AnswerStatus.needs_review, AnswerStatus.invalid}:
            return PageStatus.partial
        if question.required and answer.status not in {
            AnswerStatus.ready,
            AnswerStatus.skipped,
        }:
            return PageStatus.partial
    return PageStatus.complete


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result

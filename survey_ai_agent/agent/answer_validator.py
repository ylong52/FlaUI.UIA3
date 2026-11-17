"""答案格式与逻辑一致性校验。

原则：发现冲突或不安全的内容时，优先清空答案并返回 needs_review，
绝不擅自修改受访者真实资料。
"""

from __future__ import annotations

import re
from typing import Any

from schemas.answer import AnswerItem, AnswerSource, AnswerStatus
from schemas.question import Question, QuestionType

_ALLOWED_PERSONAL_SOURCES = {
    AnswerSource.respondent_profile,
    AnswerSource.history,
    AnswerSource.manual,
}


def validate_plan(
    answers: list[AnswerItem],
    questions: list[Question],
    profile: dict[str, Any],
    history: list[AnswerItem],
) -> tuple[list[AnswerItem], list[str]]:
    by_id = {answer.question_id: answer for answer in answers}
    history_by_id = {answer.question_id: answer for answer in history}
    dependency_map = dict(history_by_id)
    dependency_map.update(by_id)

    result: list[AnswerItem] = []
    warnings: list[str] = []

    for question in questions:
        answer = by_id.get(question.question_id)
        if answer is None:
            answer = AnswerItem(
                question_id=question.question_id,
                question_type=question.question_type,
                status=AnswerStatus.needs_review,
                notes="模型未返回该题",
            )
        answer.question_type = question.question_type
        _validate_one(answer, question, profile, dependency_map, history_by_id, warnings)
        result.append(answer)

    return result, warnings


def _validate_one(
    answer: AnswerItem,
    question: Question,
    profile: dict[str, Any],
    dependency_map: dict[str, AnswerItem],
    history_by_id: dict[str, AnswerItem],
    warnings: list[str],
) -> None:
    if question.question_type == QuestionType.unknown:
        _needs_review(answer, "题型无法可靠识别，需人工处理")
        return

    if question.options_unresolved:
        _needs_review(answer, "选项包含未解析的模板占位符（如 {{ o }}），无法安全映射")
        return

    if question.depends_on:
        dependency = dependency_map.get(question.depends_on)
        if dependency is not None:
            if dependency.status in {AnswerStatus.skipped, AnswerStatus.invalid}:
                _skip(answer, f"依赖题 {question.depends_on} 不适用")
                return
            if question.depends_value is not None and not _dependency_matches(
                dependency, question.depends_value
            ):
                _skip(answer, f"不满足条件题 {question.depends_on} 的显示条件")
                return
    elif question.hidden and answer.status == AnswerStatus.ready:
        _needs_review(answer, "题目在捕获时处于隐藏状态，且缺少条件依赖信息")
        return

    if (
        answer.status == AnswerStatus.ready
        and question.requires_personal_fact
        and answer.source not in _ALLOWED_PERSONAL_SOURCES
    ):
        _needs_review(answer, "涉及个人事实，但来源不是已确认的受访者资料/历史答案")
        return

    match question.question_type:
        case QuestionType.single_choice | QuestionType.dropdown:
            _validate_single(answer, question)
        case QuestionType.multi_choice:
            _validate_multi(answer, question)
        case QuestionType.text:
            _validate_text(answer, question)
        case QuestionType.number:
            _validate_numeric(answer, question)
        case QuestionType.rating:
            _validate_rating(answer, question)
        case QuestionType.matrix:
            _validate_matrix(answer, question)
        case QuestionType.ranking:
            _validate_ranking(answer, question)
        case _:
            _needs_review(answer, f"暂不支持的题型：{question.question_type}")

    if answer.status == AnswerStatus.ready:
        _check_age_consistency(answer, question, profile)
    if answer.status == AnswerStatus.ready:
        _check_country_consistency(answer, question, profile)
    if answer.status == AnswerStatus.ready:
        _check_history_conflict(answer, question, history_by_id)


def _validate_single(answer: AnswerItem, question: Question) -> None:
    selected = _dedupe(answer.selected_options)
    option_ids = {option.id for option in question.options}

    if len(selected) > 1:
        _needs_review(answer, "单选题只能选择一个选项")
        return
    if not selected:
        if question.required:
            _needs_review(answer, "必填单选题未作答")
        return
    if selected[0] not in option_ids:
        _needs_review(answer, f"选项 {selected[0]!r} 不存在于当前页面")
        return
    answer.selected_options = selected
    answer.answer_text = None


def _validate_multi(answer: AnswerItem, question: Question) -> None:
    selected = _dedupe(answer.selected_options)
    option_ids = {option.id for option in question.options}

    invalid = [item for item in selected if item not in option_ids]
    if invalid:
        _needs_review(answer, f"存在当前页面不存在的选项：{invalid}")
        return

    exclusive = {
        option.id for option in question.options if option.exclusive
    }
    if exclusive & set(selected) and len(selected) > 1:
        _needs_review(answer, "互斥选项（None of the above / N/A 等）不能与其他选项同时选择")
        return

    if question.min_selections is not None and len(selected) < question.min_selections:
        _needs_review(
            answer,
            f"多选题至少需要选择 {question.min_selections} 项，当前 {len(selected)} 项",
        )
        return
    if question.max_selections is not None and len(selected) > question.max_selections:
        _needs_review(
            answer,
            f"多选题最多只能选择 {question.max_selections} 项，当前 {len(selected)} 项",
        )
        return
    if question.required and not selected:
        _needs_review(answer, "必填多选题未作答")
        return

    answer.selected_options = selected
    answer.answer_text = None


def _validate_text(answer: AnswerItem, question: Question) -> None:
    text = (answer.answer_text or "").strip()
    if question.required and not text:
        _needs_review(answer, "必填文本题未作答")
        return
    answer.answer_text = text or None
    answer.selected_options = []


def _validate_numeric(answer: AnswerItem, question: Question) -> None:
    value = _numeric_value(answer)
    if value is None:
        if question.required:
            _needs_review(answer, "必填数字题未作答")
        return
    if question.numeric is not None:
        if question.numeric.min is not None and value < question.numeric.min:
            _needs_review(answer, f"数值 {value} 小于最小值 {question.numeric.min}")
            return
        if question.numeric.max is not None and value > question.numeric.max:
            _needs_review(answer, f"数值 {value} 大于最大值 {question.numeric.max}")
            return
    answer.numeric_value = value
    answer.answer_text = _format_number(value)


def _validate_rating(answer: AnswerItem, question: Question) -> None:
    value = _numeric_value(answer)
    if value is None:
        if question.required:
            _needs_review(answer, "必填评分题未作答")
        return
    if question.numeric is not None:
        if question.numeric.min is not None and value < question.numeric.min:
            _needs_review(answer, f"评分 {value} 低于最小值 {question.numeric.min}")
            return
        if question.numeric.max is not None and value > question.numeric.max:
            _needs_review(answer, f"评分 {value} 高于最大值 {question.numeric.max}")
            return
    answer.numeric_value = value
    answer.answer_text = _format_number(value)


def _validate_matrix(answer: AnswerItem, question: Question) -> None:
    if question.matrix is None:
        _needs_review(answer, "矩阵题缺少行列定义")
        return

    row_ids = {row.id for row in question.matrix.rows}
    column_ids = {column.id for column in question.matrix.columns}
    selections = dict(answer.matrix_selections)

    invalid_rows = [row for row in selections if row not in row_ids]
    invalid_columns = [
        column for column in selections.values() if column not in column_ids
    ]
    if invalid_rows or invalid_columns:
        _needs_review(
            answer,
            f"矩阵答案包含不存在的行/列：rows={invalid_rows}, columns={invalid_columns}",
        )
        return

    if question.required and set(selections) != row_ids:
        missing = sorted(row_ids - set(selections))
        _needs_review(answer, f"矩阵题未完成全部行，缺少：{missing}")
        return

    answer.matrix_selections = selections
    answer.selected_options = []


def _validate_ranking(answer: AnswerItem, question: Question) -> None:
    ranking = list(answer.ranking)
    option_ids = [option.id for option in question.options]

    if not ranking:
        if question.required:
            _needs_review(answer, "排序题未作答")
        return
    if len(set(ranking)) != len(ranking):
        _needs_review(answer, "排序题存在重复项")
        return
    if set(ranking) != set(option_ids):
        _needs_review(answer, "排序题必须包含且只包含页面中的全部选项")
        return

    answer.ranking = ranking
    answer.selected_options = []


# ---------------------------------------------------------------- consistency


def _check_age_consistency(
    answer: AnswerItem,
    question: Question,
    profile: dict[str, Any],
) -> None:
    if question.inferred_topic != "age" and not re.search(
        r"how old|\bage\b", question.text or "", re.IGNORECASE
    ):
        return
    age = _profile_age(profile)
    if age is None:
        return
    label = _selected_label(answer, question)
    if label is None:
        return
    contains = _age_range_contains(label, age)
    if contains is False:
        _needs_review(
            answer,
            f"所选年龄段 {label!r} 与受访者年龄 {age} 不一致",
        )


def _check_country_consistency(
    answer: AnswerItem,
    question: Question,
    profile: dict[str, Any],
) -> None:
    if question.inferred_topic != "country" and "country" not in (question.text or "").lower():
        return
    country = profile.get("country")
    if country is None:
        return
    label = _selected_label(answer, question)
    if label is None:
        return
    if not _country_matches(str(country), label):
        _needs_review(
            answer,
            f"所选国家 {label!r} 与受访者资料 {country!r} 不一致",
        )


def _check_history_conflict(
    answer: AnswerItem,
    question: Question,
    dependency_map: dict[str, AnswerItem],
) -> None:
    previous = dependency_map.get(question.question_id)
    if previous is None or previous is answer:
        return
    if previous.status != AnswerStatus.ready:
        return
    if answer.source != AnswerSource.llm:
        return
    if _answers_differ(previous, answer):
        _needs_review(answer, "与已确认的历史答案冲突，需人工确认")


# ---------------------------------------------------------------- helpers


def _needs_review(answer: AnswerItem, note: str) -> None:
    answer.status = AnswerStatus.needs_review
    answer.source = None
    answer.selected_options = []
    answer.answer_text = None
    answer.matrix_selections = {}
    answer.ranking = []
    answer.numeric_value = None
    answer.notes = note


def _skip(answer: AnswerItem, note: str) -> None:
    answer.status = AnswerStatus.skipped
    answer.source = None
    answer.selected_options = []
    answer.answer_text = None
    answer.matrix_selections = {}
    answer.ranking = []
    answer.numeric_value = None
    answer.notes = note


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _numeric_value(answer: AnswerItem) -> float | None:
    if answer.numeric_value is not None:
        return float(answer.numeric_value)
    text = (answer.answer_text or "").strip()
    if not text:
        return None
    cleaned = text.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _selected_label(answer: AnswerItem, question: Question) -> str | None:
    if not answer.selected_options:
        return None
    selected = answer.selected_options[0]
    for option in question.options:
        if option.id == selected:
            return option.label
    return None


def _profile_age(profile: dict[str, Any]) -> int | None:
    for key in ("age", "respondent_age", "user_age"):
        value = profile.get(key)
        if isinstance(value, (int, float)) and 0 < int(value) < 130:
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    birth_year = profile.get("birth_year")
    if isinstance(birth_year, (int, float)) and 1900 < int(birth_year) < 2100:
        return 2026 - int(birth_year)
    birthday = profile.get("birthday")
    if isinstance(birthday, str) and len(birthday) >= 4 and birthday[:4].isdigit():
        return 2026 - int(birthday[:4])
    return None


def _age_range_contains(label: str, age: int) -> bool | None:
    lower = label.lower()
    match = re.search(r"(\d{1,3})\s*[-–—]\s*(\d{1,3})", lower)
    if match:
        return int(match.group(1)) <= age <= int(match.group(2))
    match = re.search(r"(?:under|below)\s*(\d{1,3})", lower)
    if match:
        return age < int(match.group(1))
    match = re.search(r"(?:over|above)\s*(\d{1,3})", lower)
    if match:
        return age > int(match.group(1))
    if "+" in lower:
        match = re.search(r"(\d{1,3})", lower)
        if match:
            return age >= int(match.group(1))
    if lower.strip().isdigit():
        return age == int(lower.strip())
    return None


def _country_matches(profile_country: str, label: str) -> bool:
    value = profile_country.strip().lower()
    candidate = label.strip().lower()
    if value == candidate or value in candidate or candidate in value:
        return True
    aliases = {
        "us": "united states",
        "usa": "united states",
        "uk": "united kingdom",
        "gb": "united kingdom",
        "cn": "china",
        "de": "germany",
        "fr": "france",
        "au": "australia",
        "jp": "japan",
        "in": "india",
        "br": "brazil",
        "mx": "mexico",
        "ca": "canada",
        "nl": "netherlands",
        "es": "spain",
        "it": "italy",
    }
    expanded = aliases.get(value, value)
    return expanded == candidate or expanded in candidate


def _dependency_matches(dependency: AnswerItem, expected: Any) -> bool:
    expected_text = str(expected).strip().lower()
    candidates = [option.lower() for option in dependency.selected_options]
    if dependency.answer_text:
        candidates.append(dependency.answer_text.strip().lower())
    return any(
        expected_text == candidate or expected_text in candidate
        for candidate in candidates
    )


def _answers_differ(left: AnswerItem, right: AnswerItem) -> bool:
    if set(left.selected_options) != set(right.selected_options):
        return True
    if (left.answer_text or "").strip() != (right.answer_text or "").strip():
        return True
    if left.matrix_selections != right.matrix_selections:
        return True
    if left.ranking != right.ranking:
        return True
    if left.numeric_value != right.numeric_value:
        return True
    return False

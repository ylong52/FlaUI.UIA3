"""确定性答题引擎。

用途：
1. mock 模式下的答案生成；
2. 真实 LLM 模式下的“已知事实”参考。

硬性规则：只使用 respondent_profile / 已确认历史 / 调用方显式提供的结构化答案；
没有资料时返回 needs_review，不编造个人事实。
"""

from __future__ import annotations

import re
from typing import Any

from schemas.answer import AnswerItem, AnswerSource, AnswerStatus
from schemas.question import Option, Question, QuestionType

COUNTRY_CODE_MAP = {
    "us": "united states",
    "usa": "united states",
    "gb": "united kingdom",
    "uk": "united kingdom",
    "de": "germany",
    "fr": "france",
    "au": "australia",
    "jp": "japan",
    "cn": "china",
    "in": "india",
    "br": "brazil",
    "mx": "mexico",
    "ca": "canada",
    "nl": "netherlands",
    "es": "spain",
    "it": "italy",
}

KEYWORD_TO_PROFILE = (
    ("industry", "industry"),
    ("department", "department"),
    ("job title", "job_title"),
    ("occupation", "occupation"),
    ("role", "role"),
    ("email", "email"),
    ("phone", "phone"),
    ("postal", "zip"),
    ("zip", "zip"),
    ("city", "city"),
    ("subdivision", "state"),
    ("state", "state"),
    ("children", "children"),
    ("kids", "children"),
    ("household", "household_size"),
    ("income", "income"),
    ("salary", "income"),
    ("education", "education"),
    ("gender", "gender"),
    ("sex", "gender"),
    ("country", "country"),
    ("how old", "age"),
    ("age", "age"),
    ("years", "years"),
    ("experience", "years"),
    ("your name", "name"),
    ("full name", "name"),
)


class RuleAnswerEngine:
    def answer(
        self,
        questions: list[Question],
        profile: dict[str, Any],
        history: list[AnswerItem],
    ) -> list[AnswerItem]:
        normalized = _normalize_profile(profile)
        history_by_id = {
            answer.question_id: answer
            for answer in history
            if answer.status == AnswerStatus.ready
        }

        answers: list[AnswerItem] = []
        for question in questions:
            previous = history_by_id.get(question.question_id)
            if previous is not None and _options_still_valid(previous, question):
                answers.append(
                    previous.model_copy(
                        update={
                            "question_type": question.question_type,
                            "source": AnswerSource.history,
                            "notes": "复用已确认的历史答案",
                        }
                    )
                )
                continue

            answers.append(self._answer_one(question, normalized))
        return answers

    def _answer_one(
        self,
        question: Question,
        profile: dict[str, Any],
    ) -> AnswerItem:
        explicit = _lookup_structured(profile.get("answers"), question)
        if explicit is not None:
            return _answer_from_explicit(question, explicit)

        topic = question.inferred_topic or _topic_from_text(question.text)

        if topic == "age":
            result = _answer_age(question, profile)
            if result is not None:
                return result
        if topic == "country":
            result = _answer_country(question, profile)
            if result is not None:
                return result
        if topic == "gender":
            result = _answer_gender(question, profile)
            if result is not None:
                return result

        if question.question_type == QuestionType.matrix:
            return _answer_matrix(question, profile)
        if question.question_type == QuestionType.ranking:
            return _answer_ranking(question, profile)
        if question.question_type == QuestionType.rating:
            return _answer_rating(question, profile)

        key = _profile_key_for_question(question)
        if key is not None and key in profile:
            value = profile[key]
            if question.question_type in {
                QuestionType.single_choice,
                QuestionType.dropdown,
            }:
                option = _match_option(value, question.options)
                if option is not None:
                    return _ready(question, selected=[option.id], source=AnswerSource.respondent_profile)
            elif question.question_type == QuestionType.multi_choice:
                ids = _match_options(value, question.options)
                if ids:
                    return _ready(question, selected=ids, source=AnswerSource.respondent_profile)
            elif question.question_type == QuestionType.text:
                text = _as_text(value)
                if text:
                    return _ready(question, text=text, source=AnswerSource.respondent_profile)
            elif question.question_type == QuestionType.number:
                number = _as_number(value)
                if number is not None:
                    return _ready(question, number=number, source=AnswerSource.respondent_profile)

        if question.question_type == QuestionType.multi_choice:
            result = _answer_multi_from_lists(question, profile)
            if result is not None:
                return result

        if question.question_type in {
            QuestionType.single_choice,
            QuestionType.dropdown,
        }:
            # 没有明确资料时，不要猜测选项。
            return _needs_review(question, "缺少该题的受访者资料，已标记人工确认")

        if question.question_type == QuestionType.text:
            return _needs_review(question, "缺少该题的真实文本资料，mock 模式不生成主观内容")

        if question.question_type == QuestionType.number:
            return _needs_review(question, "缺少该题的数字资料")

        return _needs_review(question, "缺少该题的可用资料")


# ---------------------------------------------------------------- topics


def _answer_age(question: Question, profile: dict[str, Any]) -> AnswerItem | None:
    age = _profile_age(profile)
    if age is None:
        return None
    for option in question.options:
        if _age_range_contains(option.label, age) is True:
            return _ready(question, selected=[option.id], source=AnswerSource.respondent_profile)
    return None


def _answer_country(question: Question, profile: dict[str, Any]) -> AnswerItem | None:
    country = profile.get("country")
    if not country:
        return None
    option = _match_option(country, question.options)
    if option is not None:
        return _ready(question, selected=[option.id], source=AnswerSource.respondent_profile)
    return None


def _answer_gender(question: Question, profile: dict[str, Any]) -> AnswerItem | None:
    gender = profile.get("gender")
    if not gender:
        return None
    option = _match_option(gender, question.options)
    if option is not None:
        return _ready(question, selected=[option.id], source=AnswerSource.respondent_profile)
    return None


def _answer_matrix(question: Question, profile: dict[str, Any]) -> AnswerItem:
    explicit = _lookup_structured(profile.get("matrix_answers"), question)
    if isinstance(explicit, dict) and explicit:
        selections = {str(key): str(value) for key, value in explicit.items()}
        return _ready(question, matrix=selections, source=AnswerSource.respondent_profile)
    return _needs_review(question, "缺少矩阵题的真实资料，未生成答案")


def _answer_ranking(question: Question, profile: dict[str, Any]) -> AnswerItem:
    explicit = _lookup_structured(profile.get("ranking"), question)
    if isinstance(explicit, list) and explicit:
        return _ready(
            question,
            ranking=[str(item) for item in explicit],
            source=AnswerSource.respondent_profile,
        )
    return _needs_review(question, "缺少排序题的真实偏好，未生成答案")


def _answer_rating(question: Question, profile: dict[str, Any]) -> AnswerItem:
    explicit = _lookup_structured(profile.get("ratings"), question)
    if explicit is not None:
        number = _as_number(explicit)
        if number is not None:
            return _ready(question, number=number, source=AnswerSource.respondent_profile)
    return _needs_review(question, "缺少评分题的真实资料，未生成答案")


def _answer_multi_from_lists(
    question: Question,
    profile: dict[str, Any],
) -> AnswerItem | None:
    text = (question.text or "").lower()
    candidate_keys = []
    if "product" in text:
        candidate_keys.append("products")
    if "valve" in text:
        candidate_keys.append("valves")
    if "device" in text:
        candidate_keys.append("devices")
    if "brand" in text:
        candidate_keys.append("brands")
    candidate_keys.extend(["products", "valves", "devices"])

    for key in candidate_keys:
        value = profile.get(key)
        if not isinstance(value, (list, tuple, set)):
            continue
        ids = _match_options(list(value), question.options)
        if ids:
            return _ready(question, selected=ids, source=AnswerSource.respondent_profile)
    return None


# ---------------------------------------------------------------- explicit data


def _answer_from_explicit(question: Question, value: Any) -> AnswerItem:
    if isinstance(value, dict):
        return AnswerItem(
            question_id=question.question_id,
            question_type=question.question_type,
            selected_options=[str(item) for item in value.get("selected_options", [])],
            answer_text=value.get("answer_text"),
            matrix_selections={
                str(key): str(item)
                for key, item in (value.get("matrix_selections") or {}).items()
            },
            ranking=[str(item) for item in value.get("ranking", [])],
            numeric_value=_as_number(value.get("numeric_value")),
            status=AnswerStatus(value.get("status", AnswerStatus.ready.value)),
            source=AnswerSource(value.get("source", AnswerSource.manual.value)),
            confidence=value.get("confidence"),
            notes=value.get("notes"),
        )

    if question.question_type in {QuestionType.single_choice, QuestionType.dropdown}:
        option = _match_option(value, question.options)
        if option is not None:
            return _ready(question, selected=[option.id], source=AnswerSource.manual)
    if question.question_type == QuestionType.multi_choice:
        ids = _match_options(value, question.options)
        if ids:
            return _ready(question, selected=ids, source=AnswerSource.manual)
    if question.question_type == QuestionType.text:
        text = _as_text(value)
        if text:
            return _ready(question, text=text, source=AnswerSource.manual)
    if question.question_type in {QuestionType.number, QuestionType.rating}:
        number = _as_number(value)
        if number is not None:
            return _ready(question, number=number, source=AnswerSource.manual)

    return _needs_review(question, "显式答案无法映射到当前页面选项")


def _lookup_structured(mapping: Any, question: Question) -> Any:
    if not isinstance(mapping, dict):
        return None
    if question.question_id in mapping:
        return mapping[question.question_id]
    if question.fingerprint and question.fingerprint in mapping:
        return mapping[question.fingerprint]
    return None


# ---------------------------------------------------------------- helpers


def _normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in (profile or {}).items():
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
        if normalized:
            result[normalized] = value
    return result


def _profile_key_for_question(question: Question) -> str | None:
    text = (question.text or "").lower()
    for keyword, key in KEYWORD_TO_PROFILE:
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return key
    return None


def _topic_from_text(text: str) -> str | None:
    lower = (text or "").lower()
    if re.search(r"how old|\bage\b", lower):
        return "age"
    if "country" in lower or "reside" in lower:
        return "country"
    if "gender" in lower or re.search(r"\bsex\b", lower):
        return "gender"
    return None


def _profile_age(profile: dict[str, Any]) -> int | None:
    for key in ("age", "respondent_age", "user_age"):
        value = profile.get(key)
        if isinstance(value, (int, float)) and 0 < int(value) < 130:
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
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


def _match_option(value: Any, options: list[Option]) -> Option | None:
    if isinstance(value, (list, tuple, set)):
        if not value:
            return None
        value = next(iter(value))
    raw = str(value).strip().lower()
    if not raw:
        return None
    expanded = COUNTRY_CODE_MAP.get(raw, raw)

    for option in options:
        label = option.label.strip().lower()
        if expanded == label or raw == label:
            return option
    for option in options:
        label = option.label.strip().lower()
        if len(expanded) >= 3 and (expanded in label or label in expanded):
            return option
    return None


def _match_options(values: Any, options: list[Option]) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    ids: list[str] = []
    for value in values:
        option = _match_option(value, options)
        if option is not None and option.id not in ids:
            ids.append(option.id)
    return ids


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ready(
    question: Question,
    *,
    selected: list[str] | None = None,
    text: str | None = None,
    matrix: dict[str, str] | None = None,
    ranking: list[str] | None = None,
    number: float | None = None,
    source: AnswerSource,
) -> AnswerItem:
    return AnswerItem(
        question_id=question.question_id,
        question_type=question.question_type,
        selected_options=selected or [],
        answer_text=text,
        matrix_selections=matrix or {},
        ranking=ranking or [],
        numeric_value=number,
        status=AnswerStatus.ready,
        source=source,
    )


def _needs_review(question: Question, note: str) -> AnswerItem:
    return AnswerItem(
        question_id=question.question_id,
        question_type=question.question_type,
        status=AnswerStatus.needs_review,
        notes=note,
    )


def _options_still_valid(answer: AnswerItem, question: Question) -> bool:
    option_ids = {option.id for option in question.options}
    if question.question_type in {
        QuestionType.single_choice,
        QuestionType.multi_choice,
        QuestionType.dropdown,
    } and not answer.selected_options:
        # 选择题的 ready 答案必须有勾选，否则不能当作历史答案复用。
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

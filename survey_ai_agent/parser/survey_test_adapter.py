"""针对 api.x-survey.com/test/survey-test.html 的页面适配器。

该页面是 Vue 单文件问卷：静态 HTML 里题干是真实文本，但选项是 `{{ o }}` 等
v-for 占位符；选项数组定义在页面内联 JS 的 data() 中。C# 执行器无 CDP，
因此直接从页面源码解析题干与选项数组，生成 16 道题（Q10 拆成 4 个数字子题）。
"""

from __future__ import annotations

import html as html_lib
import re

from parser.question_extractor import compute_fingerprint
from schemas.question import (
    MatrixRow,
    MatrixSpec,
    NumericSpec,
    Option,
    Question,
    QuestionType,
)

STEP_MARKER_RE = re.compile(r"<!--[^>]*Step\s+(\d+)[^>]*-->", re.S)
Q_TITLE_RE = re.compile(
    r'<p\s+class="[^"]*qtitle[^"]*"[^>]*>(.*?)</p>', re.S | re.I
)
TAG_RE = re.compile(r"<[^>]+>")
NUM_PREFIX_RE = re.compile(r"^\s*\d+\.\s*")
WS_RE = re.compile(r"\s+")
STRING_RE = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"", re.S)

ARRAY_NAMES = (
    "ageOptions",
    "countryOptions",
    "industryOptions",
    "deptOptions",
    "productOptions",
    "roleOptions",
    "valveOptions",
    "allocRows",
    "appRows",
    "techColumns",
    "brandRows",
    "brandColumns",
    "conjointOptions",
    "rank",
)

EXPECTED_STEP_TEXTS = {
    1: 4,
    2: 2,
    3: 2,
    4: 2,
    5: 1,
    6: 1,
    7: 1,
    8: 1,
    9: 2,
}


def build_survey_test_questions(html: str) -> list[Question] | None:
    if "ageOptions" not in html or "stepCount: 9" not in html:
        return None

    arrays = {name: _js_array(html, name) for name in ARRAY_NAMES}
    if any(not arrays[name] for name in ARRAY_NAMES):
        return None

    step_texts = _step_texts(html)
    for step, count in EXPECTED_STEP_TEXTS.items():
        if len(step_texts.get(step, [])) != count:
            return None

    def text(step: int, index: int) -> str:
        return step_texts[step][index]

    questions: list[Question] = [
        _question(
            "Q1", text(1, 0), QuestionType.single_choice, 1,
            options=_options(arrays["ageOptions"]),
            inferred_topic="age",
            requires_personal_fact=True,
        ),
        _question(
            "Q2", text(1, 1), QuestionType.dropdown, 1,
            options=_options(arrays["countryOptions"]),
            inferred_topic="country",
            requires_personal_fact=True,
        ),
        _question("Q3", text(1, 2), QuestionType.text, 1),
        _question("Q4", text(1, 3), QuestionType.text, 1),
        _question(
            "Q5", text(2, 0), QuestionType.single_choice, 2,
            options=_options(arrays["industryOptions"]),
            requires_personal_fact=True,
        ),
        _question(
            "Q6", text(2, 1), QuestionType.single_choice, 2,
            options=_options(arrays["deptOptions"]),
            requires_personal_fact=True,
        ),
        _question(
            "Q7", text(3, 0), QuestionType.multi_choice, 3,
            options=_options(arrays["productOptions"], exclusive={"None of the above"}),
            min_selections=1,
            requires_personal_fact=True,
        ),
        _question(
            "Q8", text(3, 1), QuestionType.single_choice, 3,
            options=_options(arrays["roleOptions"]),
            requires_personal_fact=True,
        ),
        _question(
            "Q9", text(4, 0), QuestionType.multi_choice, 4,
            options=_options(arrays["valveOptions"]),
            min_selections=1,
            requires_personal_fact=True,
        ),
    ]

    for index, row in enumerate(arrays["allocRows"], start=1):
        questions.append(
            _question(
                f"Q10_{index}",
                f"{row} percentage",
                QuestionType.number,
                4,
                numeric=NumericSpec(min=0, max=100),
                requires_personal_fact=True,
                raw_extra={"row": row},
            )
        )

    questions.append(
        _question(
            "Q11", text(5, 0), QuestionType.matrix, 5,
            options=_options(arrays["techColumns"]),
            matrix=MatrixSpec(
                rows=_rows(arrays["appRows"]),
                columns=_options(arrays["techColumns"]),
            ),
            requires_personal_fact=True,
        )
    )
    questions.append(
        _question(
            "Q12", text(6, 0), QuestionType.matrix, 6,
            options=_options(arrays["brandColumns"]),
            matrix=MatrixSpec(
                rows=_rows(arrays["brandRows"]),
                columns=_options(arrays["brandColumns"]),
            ),
            requires_personal_fact=True,
        )
    )
    questions.append(
        _question(
            "Q13", text(7, 0), QuestionType.single_choice, 7,
            options=_options(arrays["conjointOptions"]),
        )
    )
    questions.append(_question("Q14", text(8, 0), QuestionType.text, 8))
    questions.append(
        _question(
            "Q15", text(9, 0), QuestionType.ranking, 9,
            options=_options(arrays["rank"]),
            min_selections=len(arrays["rank"]),
            max_selections=len(arrays["rank"]),
        )
    )
    questions.append(
        _question(
            "Q16", text(9, 1), QuestionType.rating, 9,
            numeric=NumericSpec(min=0, max=100, step=1),
        )
    )

    return questions


def _question(
    question_id: str,
    text: str,
    question_type: QuestionType,
    step: int,
    *,
    options: list[Option] | None = None,
    matrix: MatrixSpec | None = None,
    numeric: NumericSpec | None = None,
    min_selections: int | None = None,
    max_selections: int | None = None,
    requires_personal_fact: bool = False,
    inferred_topic: str | None = None,
    raw_extra: dict | None = None,
) -> Question:
    raw = {"step": step, "adapter": "survey-test"}
    if raw_extra:
        raw.update(raw_extra)
    question = Question(
        question_id=question_id,
        text=text,
        question_type=question_type,
        required=True,
        options=options or [],
        matrix=matrix,
        numeric=numeric,
        min_selections=min_selections,
        max_selections=max_selections,
        requires_personal_fact=requires_personal_fact,
        inferred_topic=inferred_topic,
        raw=raw,
    )
    question.fingerprint = compute_fingerprint(question)
    return question


def _options(values: list[str], exclusive: set[str] | None = None) -> list[Option]:
    exclusive = exclusive or set()
    return [
        Option(
            id=value,
            label=value,
            value=value,
            exclusive=value in exclusive,
        )
        for value in values
    ]


def _rows(values: list[str]) -> list[MatrixRow]:
    return [MatrixRow(id=value, label=value) for value in values]


def _js_array(html: str, name: str) -> list[str]:
    match = re.search(rf"\b{re.escape(name)}\s*:\s*\[(.*?)\]", html, re.S)
    if match is None:
        return []
    return [_unescape(single or double) for single, double in STRING_RE.findall(match.group(1))]


def _unescape(value: str) -> str:
    return (
        value.replace("\\'", "'")
        .replace('\\"', '"')
        .replace("\\n", " ")
        .replace("\\r", " ")
        .replace("\\t", " ")
    )


def _step_texts(html: str) -> dict[int, list[str]]:
    markers = list(STEP_MARKER_RE.finditer(html))
    result: dict[int, list[str]] = {}
    for index, marker in enumerate(markers):
        step = int(marker.group(1))
        end = markers[index + 1].start() if index + 1 < len(markers) else len(html)
        segment = html[marker.end() : end]
        texts: list[str] = []
        for title in Q_TITLE_RE.finditer(segment):
            raw = html_lib.unescape(TAG_RE.sub("", title.group(1)))
            cleaned = WS_RE.sub(" ", raw).strip()
            cleaned = NUM_PREFIX_RE.sub("", cleaned).strip()
            if cleaned:
                texts.append(cleaned)
        result[step] = texts
    return result

from __future__ import annotations

from parser.question_extractor import extract_questions
from schemas.question import Question, QuestionType


def by_id(questions: list[Question], question_id: str) -> Question:
    for question in questions:
        if question.question_id == question_id:
            return question
    raise AssertionError(f"question {question_id} not found")


def test_extracts_all_question_types(fixture_html: str) -> None:
    questions = extract_questions(fixture_html)

    assert len(questions) == 11
    assert by_id(questions, "Q1").question_type == QuestionType.single_choice
    assert by_id(questions, "Q2").question_type == QuestionType.dropdown
    assert by_id(questions, "Q3").question_type == QuestionType.text
    assert by_id(questions, "Q4").question_type == QuestionType.multi_choice
    assert by_id(questions, "Q5").question_type == QuestionType.matrix
    assert by_id(questions, "Q6").question_type == QuestionType.rating
    assert by_id(questions, "Q7").question_type == QuestionType.ranking
    assert by_id(questions, "Q8").question_type == QuestionType.number


def test_choice_options_and_required(fixture_html: str) -> None:
    questions = extract_questions(fixture_html)

    q1 = by_id(questions, "Q1")
    assert q1.required is True
    assert [option.id for option in q1.options] == ["18-24", "25-34", "35-44"]
    assert q1.inferred_topic == "age"
    assert q1.requires_personal_fact is True

    q2 = by_id(questions, "Q2")
    assert [option.id for option in q2.options] == ["US", "CN", "DE"]

    q4 = by_id(questions, "Q4")
    assert [option.id for option in q4.options] == ["Pumps", "Valves", "none"]
    assert any(option.exclusive for option in q4.options)
    assert q4.min_selections == 1
    assert q4.requires_personal_fact is True


def test_personal_fact_classification(fixture_html: str) -> None:
    questions = extract_questions(fixture_html)

    # 主观开放题/排序题不应被当成可核验的个人事实
    assert by_id(questions, "Q3").requires_personal_fact is False
    assert by_id(questions, "Q6").requires_personal_fact is False
    assert by_id(questions, "Q7").requires_personal_fact is False

    # 年龄/产品使用/矩阵公司实践属于个人事实
    assert by_id(questions, "Q1").requires_personal_fact is True
    assert by_id(questions, "Q4").requires_personal_fact is True
    assert by_id(questions, "Q5").requires_personal_fact is True


def test_matrix_extraction(fixture_html: str) -> None:
    q5 = by_id(extract_questions(fixture_html), "Q5")

    assert q5.matrix is not None
    assert [row.label for row in q5.matrix.rows] == ["Isolation", "Control"]
    assert [column.label for column in q5.matrix.columns] == [
        "Concentric",
        "Double Offset",
    ]
    assert [column.id for column in q5.matrix.columns] == ["C", "D"]


def test_ranking_and_numeric_extraction(fixture_html: str) -> None:
    questions = extract_questions(fixture_html)

    q7 = by_id(questions, "Q7")
    assert [option.id for option in q7.options] == ["price", "support", "delivery"]
    assert [option.label for option in q7.options] == [
        "Price",
        "Support",
        "Delivery",
    ]
    assert q7.min_selections == q7.max_selections == 3

    q8 = by_id(questions, "Q8")
    assert q8.numeric is not None
    assert q8.numeric.min == 0
    assert q8.numeric.max == 60


def test_conditional_metadata(fixture_html: str) -> None:
    q9 = by_id(extract_questions(fixture_html), "Q9")

    assert q9.depends_on == "Q4"
    assert q9.depends_value == "Valves"


def test_image_only_title_falls_back_to_inferred_topic(fixture_html: str) -> None:
    q10 = by_id(extract_questions(fixture_html), "Q10")

    assert q10.text == ""
    assert q10.text_unavailable is True
    assert q10.inferred_topic == "gender"
    assert [option.id for option in q10.options] == ["male", "female", "other"]


def test_unresolved_template_options_are_flagged(fixture_html: str) -> None:
    q11 = by_id(extract_questions(fixture_html), "Q11")

    assert q11.options_unresolved is True

from __future__ import annotations

from agent.answer_validator import validate_plan
from schemas.answer import AnswerItem, AnswerSource, AnswerStatus
from schemas.question import (
    MatrixRow,
    MatrixSpec,
    NumericSpec,
    Option,
    Question,
    QuestionType,
)


def single_question(**overrides) -> Question:
    data = {
        "question_id": "Q1",
        "text": "Pick one",
        "question_type": QuestionType.single_choice,
        "required": True,
        "options": [Option(id="a", label="A"), Option(id="b", label="B")],
    }
    data.update(overrides)
    return Question(**data)


def ready(question: Question, **overrides) -> AnswerItem:
    data = {
        "question_id": question.question_id,
        "question_type": question.question_type,
        "status": AnswerStatus.ready,
        "source": AnswerSource.respondent_profile,
    }
    data.update(overrides)
    return AnswerItem(**data)


def only(result: list[AnswerItem], question_id: str = "Q1") -> AnswerItem:
    return next(answer for answer in result if answer.question_id == question_id)


def test_single_choice_rejects_multiple_options() -> None:
    question = single_question()
    answer = ready(question, selected_options=["a", "b"])

    result, _ = validate_plan([answer], [question], {}, [])

    assert only(result).status == AnswerStatus.needs_review
    assert only(result).selected_options == []


def test_single_choice_rejects_unknown_option() -> None:
    question = single_question()
    answer = ready(question, selected_options=["x"])

    result, _ = validate_plan([answer], [question], {}, [])

    assert only(result).status == AnswerStatus.needs_review


def test_multi_choice_rejects_exclusive_combination() -> None:
    question = Question(
        question_id="Q1",
        text="Pick many",
        question_type=QuestionType.multi_choice,
        required=True,
        options=[
            Option(id="a", label="A"),
            Option(id="none", label="None of the above", exclusive=True),
        ],
        min_selections=1,
    )
    answer = ready(question, selected_options=["a", "none"])

    result, _ = validate_plan([answer], [question], {}, [])

    assert only(result).status == AnswerStatus.needs_review


def test_matrix_requires_all_rows() -> None:
    question = Question(
        question_id="Q1",
        text="Matrix",
        question_type=QuestionType.matrix,
        required=True,
        options=[Option(id="c1", label="C1")],
        matrix=MatrixSpec(
            rows=[MatrixRow(id="r1", label="R1"), MatrixRow(id="r2", label="R2")],
            columns=[Option(id="c1", label="C1")],
        ),
    )
    answer = ready(question, matrix_selections={"r1": "c1"})

    result, _ = validate_plan([answer], [question], {}, [])

    assert only(result).status == AnswerStatus.needs_review


def test_ranking_requires_full_permutation() -> None:
    question = Question(
        question_id="Q1",
        text="Rank",
        question_type=QuestionType.ranking,
        required=True,
        options=[Option(id="a", label="A"), Option(id="b", label="B")],
    )
    answer = ready(question, ranking=["a"])

    result, _ = validate_plan([answer], [question], {}, [])

    assert only(result).status == AnswerStatus.needs_review


def test_numeric_out_of_range() -> None:
    question = Question(
        question_id="Q1",
        text="Years",
        question_type=QuestionType.number,
        required=True,
        numeric=NumericSpec(min=0, max=60),
    )
    answer = ready(question, numeric_value=99)

    result, _ = validate_plan([answer], [question], {}, [])

    assert only(result).status == AnswerStatus.needs_review


def test_age_mismatch_is_flagged() -> None:
    question = single_question(
        text="How old are you?",
        options=[Option(id="25-34", label="25-34")],
        inferred_topic="age",
    )
    answer = ready(question, selected_options=["25-34"])

    result, _ = validate_plan([answer], [question], {"age": 45}, [])

    assert only(result).status == AnswerStatus.needs_review
    assert "年龄" in (only(result).notes or "")


def test_llm_cannot_answer_personal_fact() -> None:
    question = single_question(requires_personal_fact=True)
    answer = ready(question, selected_options=["a"], source=AnswerSource.llm)

    result, _ = validate_plan([answer], [question], {}, [])

    assert only(result).status == AnswerStatus.needs_review


def test_conditional_question_is_skipped_when_dependency_unmet() -> None:
    gate = single_question(
        question_id="Q1",
        text="Do you use valves?",
        options=[Option(id="yes", label="Yes"), Option(id="no", label="No")],
    )
    conditional = Question(
        question_id="Q2",
        text="Which valve?",
        question_type=QuestionType.single_choice,
        required=True,
        options=[Option(id="ball", label="Ball")],
        depends_on="Q1",
        depends_value="yes",
    )
    answers = [
        ready(gate, selected_options=["no"]),
        ready(conditional, selected_options=["ball"]),
    ]

    result, _ = validate_plan(answers, [gate, conditional], {}, [])

    assert only(result, "Q2").status == AnswerStatus.skipped
    assert only(result, "Q1").status == AnswerStatus.ready

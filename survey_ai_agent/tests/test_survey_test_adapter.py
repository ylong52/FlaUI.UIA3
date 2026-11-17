from __future__ import annotations

import json
from pathlib import Path

from agent.model_client import LLMResult
from agent.question_analyzer import LLMAnswer, LLMPlan
from agent.survey_agent import SurveyAnalyzer
from config import Settings
from parser.survey_test_adapter import build_survey_test_questions
from schemas.answer import AnswerSource, AnswerStatus, PageStatus, Usage
from schemas.question import QuestionType
from schemas.request import AnalyzeRequest
from storage.memory_store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
RAW_HTML = (Path(__file__).parent / "fixtures" / "survey-test-raw.html").read_text(
    encoding="utf-8"
)
PROFILE = json.loads((ROOT / "demo_profile.json").read_text(encoding="utf-8"))


def test_adapter_extracts_all_questions_and_steps() -> None:
    questions = build_survey_test_questions(RAW_HTML)

    assert questions is not None
    assert len(questions) == 19
    by_id = {question.question_id: question for question in questions}

    assert sorted({question.raw["step"] for question in questions}) == list(range(1, 10))
    assert by_id["Q11"].matrix is not None
    assert len(by_id["Q11"].matrix.rows) == 4
    assert len(by_id["Q11"].matrix.columns) == 5
    assert by_id["Q12"].matrix is not None
    assert len(by_id["Q12"].matrix.rows) == 4
    assert len(by_id["Q12"].matrix.columns) == 8
    assert by_id["Q15"].question_type == QuestionType.ranking
    assert len(by_id["Q15"].options) == 6
    assert by_id["Q10_1"].numeric is not None
    assert by_id["Q10_1"].numeric.max == 100


class TextOnlyLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.sent_ids: list[str] = []

    async def analyze(self, **kwargs) -> LLMResult:
        self.calls += 1
        self.sent_ids = [question.question_id for question in kwargs["questions"]]
        answers = [
            LLMAnswer(
                question_id=question.question_id,
                answer_text="A natural answer for the open-ended question.",
            )
            for question in kwargs["questions"]
            if question.question_type == QuestionType.text
        ]
        for question in kwargs["questions"]:
            if question.question_type != QuestionType.text:
                answers.append(
                    LLMAnswer(question_id=question.question_id, status="needs_review")
                )
        return LLMResult(
            plan=LLMPlan(answers=answers),
            usage=Usage(model="fake", total_tokens=10),
            model="fake",
        )


async def test_adapter_produces_complete_plan_with_profile() -> None:
    fake = TextOnlyLLM()
    analyzer = SurveyAnalyzer(
        Settings(_env_file=None, llm_mode="deepseek"),
        MemoryStore(),
        llm=fake,
    )
    request = AnalyzeRequest(
        task_id="adapter-test",
        page_id="full-page",
        html=RAW_HTML,
        respondent_profile=PROFILE,
    )

    response = await analyzer.analyze(request)
    answers = {answer.question_id: answer for answer in response.answers}

    assert response.status == PageStatus.complete
    assert set(fake.sent_ids) == {"Q3", "Q4", "Q14"}
    assert fake.calls == 1

    for question_id, answer in answers.items():
        assert answer.status == AnswerStatus.ready, (question_id, answer.notes)

    assert answers["Q3"].source == AnswerSource.llm
    assert answers["Q4"].source == AnswerSource.llm
    assert answers["Q14"].source == AnswerSource.llm
    assert answers["Q11"].matrix_selections == PROFILE["matrix_answers"]["Q11"]
    assert answers["Q12"].matrix_selections == PROFILE["matrix_answers"]["Q12"]
    assert answers["Q15"].ranking == PROFILE["ranking"]["Q15"]
    assert answers["Q16"].numeric_value == 85
    assert answers["Q13"].selected_options == [PROFILE["answers"]["Q13"]]
    assert answers["Q10_1"].numeric_value == 40
    assert answers["Q10_2"].numeric_value == 30
    assert answers["Q10_3"].numeric_value == 20
    assert answers["Q10_4"].numeric_value == 10

from __future__ import annotations

from agent.model_client import LLMResult
from agent.question_analyzer import LLMAnswer, LLMPlan
from agent.survey_agent import SurveyAnalyzer
from config import Settings
from schemas.answer import AnswerSource, AnswerStatus, PageStatus, Usage
from schemas.question import QuestionType
from schemas.request import AnalyzeRequest
from storage.memory_store import MemoryStore


def build_request(html: str, profile: dict, task_id: str = "task-1") -> AnalyzeRequest:
    return AnalyzeRequest(
        task_id=task_id,
        page_id="page-1",
        html=html,
        respondent_profile=profile,
    )


async def test_mock_analysis_uses_only_confirmed_facts(
    fixture_html: str, profile: dict
) -> None:
    analyzer = SurveyAnalyzer(Settings(_env_file=None, llm_mode="mock"), MemoryStore())

    response = await analyzer.analyze(build_request(fixture_html, profile))
    answers = {answer.question_id: answer for answer in response.answers}

    assert response.status == PageStatus.partial
    assert answers["Q1"].status == AnswerStatus.ready
    assert answers["Q1"].selected_options == ["25-34"]
    assert answers["Q1"].source == AnswerSource.respondent_profile

    assert answers["Q2"].selected_options == ["CN"]
    assert answers["Q4"].selected_options == ["Pumps"]
    assert answers["Q8"].numeric_value == 5

    # 没有资料的主观题/个人事实题不得编造
    assert answers["Q3"].status == AnswerStatus.needs_review
    assert answers["Q5"].status == AnswerStatus.needs_review
    assert answers["Q6"].status == AnswerStatus.needs_review
    assert answers["Q7"].status == AnswerStatus.needs_review
    assert answers["Q11"].status == AnswerStatus.needs_review

    # Q9 依赖 Q4=Valves，而资料只选了 Pumps → skipped
    assert answers["Q9"].status == AnswerStatus.skipped

    for answer in response.answers:
        if answer.status == AnswerStatus.ready:
            question = next(
                q for q in response.questions if q.question_id == answer.question_id
            )
            option_ids = {option.id for option in question.options}
            assert set(answer.selected_options) <= option_ids


async def test_second_page_reuses_verified_answers(
    fixture_html: str, profile: dict
) -> None:
    store = MemoryStore()
    analyzer = SurveyAnalyzer(Settings(_env_file=None, llm_mode="mock"), store)
    request = build_request(fixture_html, profile)

    await analyzer.analyze(request)
    second = await analyzer.analyze(request)
    answers = {answer.question_id: answer for answer in second.answers}

    for question_id in ("Q1", "Q2", "Q4", "Q8"):
        assert answers[question_id].status == AnswerStatus.ready
        assert answers[question_id].source == AnswerSource.history


async def test_image_only_title_uses_inferred_topic() -> None:
    html = """
    <div class="qblock" data-question-id="G">
      <p class="qtitle"><img src="x" alt=""></p>
      <label><input type="radio" name="g" value="male"><span>Male</span></label>
      <label><input type="radio" name="g" value="female"><span>Female</span></label>
      <label><input type="radio" name="g" value="other"><span>Other</span></label>
    </div>
    """
    analyzer = SurveyAnalyzer(Settings(_env_file=None, llm_mode="mock"), MemoryStore())

    response = await analyzer.analyze(build_request(html, {"gender": "female"}))
    answer = response.answers[0]

    assert answer.status == AnswerStatus.ready
    assert answer.selected_options == ["female"]
    assert response.questions[0].text_unavailable is True
    assert response.questions[0].inferred_topic == "gender"


async def test_unknown_template_options_are_not_answered(
    fixture_html: str, profile: dict
) -> None:
    analyzer = SurveyAnalyzer(Settings(_env_file=None, llm_mode="mock"), MemoryStore())

    response = await analyzer.analyze(build_request(fixture_html, profile))
    answer = next(a for a in response.answers if a.question_id == "Q11")

    assert answer.status == AnswerStatus.needs_review
    assert "模板" in (answer.notes or "")


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, **kwargs) -> LLMResult:
        self.calls += 1
        answers: list[LLMAnswer] = []
        for question in kwargs["questions"]:
            if question.question_type == QuestionType.text:
                answers.append(
                    LLMAnswer(
                        question_id=question.question_id,
                        answer_text="A short, natural answer.",
                    )
                )
            elif question.question_type in {
                QuestionType.single_choice,
                QuestionType.dropdown,
            }:
                answers.append(
                    LLMAnswer(
                        question_id=question.question_id,
                        selected_options=[question.options[0].id],
                    )
                )
            else:
                answers.append(
                    LLMAnswer(question_id=question.question_id, status="needs_review")
                )
        return LLMResult(
            plan=LLMPlan(answers=answers),
            usage=Usage(
                model="fake",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            model="fake",
        )


async def test_rule_prefill_keeps_personal_facts_out_of_llm(
    fixture_html: str, profile: dict
) -> None:
    class RecordingFakeLLM(FakeLLM):
        def __init__(self) -> None:
            super().__init__()
            self.sent: list[list[str]] = []

        async def analyze(self, **kwargs) -> LLMResult:
            self.sent.append([question.question_id for question in kwargs["questions"]])
            return await super().analyze(**kwargs)

    fake = RecordingFakeLLM()
    analyzer = SurveyAnalyzer(
        Settings(_env_file=None, llm_mode="deepseek"), MemoryStore(), llm=fake
    )

    response = await analyzer.analyze(build_request(fixture_html, profile))
    answers = {answer.question_id: answer for answer in response.answers}
    sent_ids = fake.sent[0]

    for question_id in ("Q1", "Q2", "Q4", "Q8"):
        assert question_id not in sent_ids
        assert answers[question_id].status == AnswerStatus.ready
        assert answers[question_id].source == AnswerSource.respondent_profile

    assert "Q3" in sent_ids  # 主观开放题交由模型
    assert fake.calls == 1


async def test_incremental_analysis_skips_llm_for_unchanged_verified_questions() -> None:
    html = """
    <div class="qblock" data-question-id="C">
      <p class="qtitle">What is your favorite color?</p>
      <label><input type="radio" name="c" value="red"><span>Red</span></label>
      <label><input type="radio" name="c" value="blue"><span>Blue</span></label>
    </div>
    <div class="qblock" data-question-id="T">
      <p class="qtitle">Tell us about your day.</p>
      <textarea name="t"></textarea>
    </div>
    """
    fake = FakeLLM()
    settings = Settings(_env_file=None, llm_mode="deepseek")
    analyzer = SurveyAnalyzer(settings, MemoryStore(), llm=fake)
    request = build_request(html, {})

    first = await analyzer.analyze(request)
    assert fake.calls == 1
    assert first.status == PageStatus.complete

    second = await analyzer.analyze(request)
    assert fake.calls == 1  # 未调用模型
    assert {a.source for a in second.answers} == {AnswerSource.history}
    assert second.usage.total_tokens == 0

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agent.model_client import DeepSeekLLM
from agent.question_analyzer import INSTRUCTIONS, LLMPlan
from config import Settings


def test_pydantic_ai_structured_output_contract() -> None:
    agent = Agent(TestModel(), output_type=LLMPlan, instructions=INSTRUCTIONS)

    result = agent.run_sync("produce an answer plan")

    assert isinstance(result.output, LLMPlan)
    assert result.usage is not None


def test_deepseek_agent_builds_without_network(monkeypatch) -> None:
    monkeypatch.setenv("SURVEY_AI_DEEPSEEK_API_KEY", "dummy-key-for-construction")
    settings = Settings(_env_file=None, llm_mode="deepseek")

    llm = DeepSeekLLM(settings)
    agent = llm._build_agent()

    assert llm.configured is True
    assert agent is not None
    assert settings.deepseek_model

    tools = set(agent._function_toolset.tools)  # noqa: SLF001 - 契约测试
    assert {"lookup_profile_fact", "lookup_history_answer"} <= tools

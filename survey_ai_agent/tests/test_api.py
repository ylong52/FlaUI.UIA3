from __future__ import annotations

from fastapi.testclient import TestClient

from api.routes import create_app
from config import Settings
from storage.memory_store import MemoryStore


def payload(fixture_html: str, profile: dict) -> dict:
    return {
        "task_id": "task-api",
        "page_id": "page-1",
        "html": fixture_html,
        "respondent_profile": profile,
    }


def test_analyze_mock_mode_returns_valid_plan(
    fixture_html: str, profile: dict
) -> None:
    app = create_app(Settings(_env_file=None, llm_mode="mock"), MemoryStore())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/analyze",
            json=payload(fixture_html, profile),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["task_id"] == "task-api"
        assert body["page_id"] == "page-1"
        assert body["status"] == "partial"
        assert body["answers"]

        questions = {question["question_id"]: question for question in body["questions"]}
        for answer in body["answers"]:
            assert answer["question_id"] in questions
            option_ids = {option["id"] for option in questions[answer["question_id"]]["options"]}
            assert set(answer["selected_options"]) <= option_ids

        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["db"]["ok"] is True
        assert health.json()["llm"]["mode"] == "mock"

        context = client.get("/api/v1/tasks/task-api/context")
        assert context.status_code == 200
        assert context.json()["context"]["profile"]["age"] == 29

        missing = client.get("/api/v1/tasks/unknown/context")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "context_not_found"


def test_deepseek_without_key_returns_explicit_error(
    fixture_html: str, profile: dict, monkeypatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SURVEY_AI_DEEPSEEK_API_KEY", raising=False)
    # 测试隔离：不读取项目 .env，确保没有真实 Key、不会发出外部请求。
    settings = Settings(_env_file=None, llm_mode="deepseek")
    app = create_app(settings, MemoryStore())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/analyze",
            json=payload(fixture_html, profile),
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_not_configured"


def test_no_questions_returns_400() -> None:
    app = create_app(Settings(_env_file=None, llm_mode="mock"), MemoryStore())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/analyze",
            json={
                "task_id": "task-api",
                "page_id": "p",
                "html": "<html><body><p>No controls here</p></body></html>",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_questions"


def test_request_validation_error() -> None:
    app = create_app(Settings(_env_file=None, llm_mode="mock"), MemoryStore())

    with TestClient(app) as client:
        response = client.post("/api/v1/agent/analyze", json={"task_id": "x"})

    assert response.status_code == 422

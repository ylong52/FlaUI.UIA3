"""FastAPI 路由与错误映射。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent.model_client import LLMConfigurationError, LLMUpstreamError
from agent.survey_agent import NoQuestionsError, SurveyAnalyzer
from config import Settings
from schemas.answer import AnalyzeResponse
from schemas.request import AnalyzeRequest
from storage.base import StoreError, SurveyStore
from storage.mysql_store import MySQLStore

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    store: SurveyStore | None = None,
    llm: Any = None,
) -> FastAPI:
    settings = settings or Settings()
    store = store or MySQLStore(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await store.init()
        except StoreError as exc:
            logger.error("数据库初始化失败：%s", exc)
            app.state.store_error = str(exc)
        try:
            yield
        finally:
            await store.close()

    app = FastAPI(
        title="survey-ai-agent",
        version="0.1.0",
        description="AI survey analysis and answering service",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.analyzer = SurveyAnalyzer(settings, store, llm=llm)
    app.state.store_error = None

    @app.exception_handler(NoQuestionsError)
    async def _no_questions(_: Request, exc: NoQuestionsError) -> JSONResponse:
        return _error(400, exc.code, str(exc))

    @app.exception_handler(LLMConfigurationError)
    async def _llm_config(_: Request, exc: LLMConfigurationError) -> JSONResponse:
        return _error(502, exc.code, str(exc))

    @app.exception_handler(LLMUpstreamError)
    async def _llm_upstream(_: Request, exc: LLMUpstreamError) -> JSONResponse:
        return _error(502, exc.code, str(exc))

    @app.exception_handler(StoreError)
    async def _store(_: Request, exc: StoreError) -> JSONResponse:
        return _error(503, exc.code, str(exc))

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常：%s %s", request.method, request.url.path)
        return _error(500, "internal_error", "服务内部错误，请查看日志")

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, Any]:
        current_settings: Settings = request.app.state.settings
        db_ok = await request.app.state.store.ping()
        return {
            "status": "ok" if db_ok else "degraded",
            "service": current_settings.app_name,
            "db": {"ok": db_ok, "database": current_settings.db_name},
            "llm": {
                "mode": current_settings.effective_llm_mode,
                "configured": current_settings.deepseek_configured,
                "model": current_settings.deepseek_model,
                "base_url": current_settings.deepseek_base_url,
            },
        }

    @app.post("/api/v1/agent/analyze", response_model=AnalyzeResponse)
    async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
        return await request.app.state.analyzer.analyze(payload)

    @app.get("/api/v1/tasks/{task_id}/context")
    async def get_context(task_id: str, request: Request) -> dict[str, Any]:
        context = await request.app.state.store.get_context(task_id)
        if context is None:
            return _error(404, "context_not_found", f"任务 {task_id} 没有已保存的上下文")
        return {"task_id": task_id, "context": context}

    return app


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )

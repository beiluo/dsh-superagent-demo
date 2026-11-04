"""FastAPI application for the ontology agent."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .agent import AgentService
from .llm import LLMClient
from .marketdata import EastmoneyProvider, MarketDataProvider
from .ontology import OntologyStore
from .query import METRIC_FIELDS
from .security import SlidingWindowLimiter, client_ip
from .settings import Settings
from .tools import LLM_TOOL_NAMES, TOOLS

logger = logging.getLogger("ashare.agent.api")

SERVICE_NAME = "ashare-ontology-agent"
SERVICE_VERSION = "1.8.0"

DISCLAIMER = (
    "示例公司数据为合成示例；真实 A 股数据来自公开行情与年报接口，可能延迟。"
    "不构成投资建议，不连接交易通道。"
)


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str = ""
    content: str = ""


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str = Field(default="")
    history: list[HistoryItem] | None = None


def _security_headers(response: JSONResponse, request_id: str, *, api: bool = True) -> JSONResponse:
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["X-Frame-Options"] = "DENY"
    if api:
        response.headers["Cache-Control"] = "no-store"
    return response


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "requestId": request_id,
        },
        headers=headers,
    )


def create_app(
    *,
    settings: Settings | None = None,
    store: OntologyStore | None = None,
    llm: LLMClient | None = None,
    market_data: MarketDataProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if store is None:
        if market_data is None and settings.market_data_enabled:
            market_data = EastmoneyProvider(
                timeout_seconds=settings.market_data_timeout_seconds,
                quote_ttl_seconds=settings.market_data_quote_ttl_seconds,
                financial_ttl_seconds=settings.market_data_financial_ttl_seconds,
                short_term_ttl_seconds=settings.market_data_short_term_ttl_seconds,
            )
        store = OntologyStore(settings.root, market_data=market_data)
    elif market_data is not None:
        store.market_data = market_data
    service = AgentService(store, settings, llm=llm)
    limiter = SlidingWindowLimiter(
        per_minute=settings.rate_limit_per_minute,
        per_hour=settings.rate_limit_per_hour,
        daily_budget=settings.daily_request_budget,
    )
    app = FastAPI(
        title="A-Share Ontology Agent",
        description="Server-side, ontology-grounded stock-analysis agent for the demo site.",
        version=SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.service = service
    app.state.limiter = limiter

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-Id", "X-Agent-Mode"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        path = request.url.path

        if request.method == "POST" and path.startswith("/api/"):
            declared = request.headers.get("content-length")
            if declared:
                try:
                    if int(declared) > settings.max_request_bytes:
                        return _security_headers(
                            _error(
                                413,
                                "request_too_large",
                                "请求体过大。",
                                request_id=request_id,
                            ),
                            request_id,
                        )
                except ValueError:
                    pass
            body = await request.body()
            if len(body) > settings.max_request_bytes:
                return _security_headers(
                    _error(
                        413,
                        "request_too_large",
                        "请求体过大。",
                        request_id=request_id,
                    ),
                    request_id,
                )

        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - keep internals out of the response
            logger.exception("unhandled request error request_id=%s path=%s", request_id, path)
            response = _error(500, "internal_error", "服务内部错误。", request_id=request_id)

        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["X-Frame-Options"] = "DENY"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(
            400,
            "invalid_request",
            "请求格式不正确。",
            request_id=getattr(request.state, "request_id", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled application error")
        return _error(
            500,
            "internal_error",
            "服务内部错误。",
            request_id=getattr(request.state, "request_id", None),
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

    @app.get("/api/agent/status")
    async def agent_status() -> dict[str, Any]:
        enabled = bool(service.llm.enabled)
        return {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "mode": "llm" if enabled else "rules",
            "llm": {
                "configured": enabled,
                "provider": settings.provider,
                "model": settings.llm_model if enabled else None,
            },
            "limits": {
                "maxQuestionChars": settings.max_question_chars,
                "rateLimitPerHour": settings.rate_limit_per_hour,
                "dailyRequestBudget": settings.daily_request_budget,
            },
            "ontology": {
                "triples": len(store.graph),
                "companies": len(store._company_subjects),
                "rules": len(store.rules()),
            },
            "companies": store.company_names(),
            "query": {
                "tools": list(LLM_TOOL_NAMES),
                "rulesFallbackTools": [
                    tool["function"]["name"]
                    for tool in TOOLS
                    if tool["function"]["name"] not in LLM_TOOL_NAMES
                ],
                "freeQuery": {
                    "enabled": enabled,
                    "forms": ["SELECT", "ASK"],
                    "maxRows": 50,
                    "note": (
                        "LLM 模式只用图式发现、真实事实加载和自生成只读 SPARQL 驱动本体；"
                        "固定分析工具仅用于规则回退。"
                    ),
                },
                "metrics": list(METRIC_FIELDS),
                "realScreening": store.market_data is not None,
                "realScreeningScope": "东方财富行情接口单页样本（最多 200 只），仅行情/估值字段",
            },
            "marketData": {
                "enabled": store.market_data is not None,
                "provider": getattr(store.market_data, "source_label", None),
                "scope": "真实 A 股（6 位证券代码或证券简称）",
                "note": "公开行情与年报接口，可能延迟；不连接交易通道。",
            },
            "disclaimer": DISCLAIMER,
            "keyHandling": "LLM_API_KEY 只存在于服务端环境变量；浏览器不会收到密钥。",
        }

    @app.post("/api/agent/analyze")
    async def analyze(request: Request, payload: AnalyzeRequest) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        question = (payload.question or "").strip()
        if not question:
            return _error(400, "empty_question", "请输入问题。", request_id=request_id)
        if len(question) > settings.max_question_chars:
            return _error(
                400,
                "question_too_long",
                f"问题最多 {settings.max_question_chars} 个字符。",
                request_id=request_id,
            )

        ip = client_ip(request, trust_proxy=settings.trust_proxy)
        allowed, retry_after, reason = limiter.check(ip)
        if not allowed:
            messages = {
                "per_minute": "请求过于频繁，请稍后再试。",
                "per_hour": "本小时请求次数已达上限，请稍后再试。",
                "daily_budget": "今日演示额度已用完，请明天再试。",
            }
            return _error(
                429,
                "rate_limited",
                messages.get(reason, "请求过于频繁，请稍后再试。"),
                request_id=request_id,
                headers={"Retry-After": str(retry_after)},
            )

        history = [item.model_dump() for item in (payload.history or [])]
        started = time.perf_counter()
        if not hasattr(request.app.state, "semaphore"):
            request.app.state.semaphore = asyncio.Semaphore(settings.max_concurrency)
        async with request.app.state.semaphore:
            result = await service.analyze(question, history)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        body = {
            "requestId": request_id,
            "elapsedMs": elapsed_ms,
            **result.to_dict(),
        }
        response = JSONResponse(body)
        response.headers["X-Agent-Mode"] = result.mode
        return response

    if settings.serve_static:
        _mount_static(app, settings.root)

    return app


def _mount_static(app: FastAPI, root: Path) -> None:
    for route, directory in (
        ("/assets", root / "assets"),
        ("/ontology", root / "ontology"),
        ("/docs", root / "docs"),
    ):
        if directory.is_dir():
            app.mount(route, StaticFiles(directory=directory), name=route.strip("/"))

    index = root / "index.html"
    if index.is_file():

        @app.get("/", include_in_schema=False)
        async def index_page() -> FileResponse:
            return FileResponse(index, media_type="text/html; charset=utf-8")

        @app.get("/index.html", include_in_schema=False)
        async def index_page_alias() -> FileResponse:
            return FileResponse(index, media_type="text/html; charset=utf-8")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)


__all__ = ["SERVICE_NAME", "SERVICE_VERSION", "create_app"]

"""
MCP Server 1 — FastAPI application.

Exposes data-pipeline tools as HTTP endpoints with built-in
rate limiting, request caching, and connection pooling.

Run:
    uvicorn mcp_server_1.main:app --host 0.0.0.0 --port 8100 --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Query
from pydantic import BaseModel

from .cache import request_cache
from .config import get_settings
from .rate_limiter import rate_limiter

logger = logging.getLogger("mcp_server_1")
settings = get_settings()

# ── Shared httpx connection pool ─────────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown of shared resources."""
    global _http_client

    # Configure rate limiters
    rate_limiter.configure("yfinance", settings.RATE_LIMIT_YFINANCE)
    rate_limiter.configure("fred", settings.RATE_LIMIT_FRED)
    rate_limiter.configure("rbi", settings.RATE_LIMIT_RBI)
    rate_limiter.configure("nse", settings.RATE_LIMIT_NSE)

    # Create shared httpx client with connection pooling
    _http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.HTTP_POOL_MAX_CONNECTIONS,
            max_keepalive_connections=settings.HTTP_POOL_MAX_KEEPALIVE,
        ),
        timeout=httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS),
    )

    logger.info("MCP Server 1 started — rate limiters and connection pool ready")
    yield

    # Cleanup
    if _http_client:
        await _http_client.aclose()
    request_cache.clear()
    logger.info("MCP Server 1 shut down")


def get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx connection-pooled client."""
    if _http_client is None:
        raise RuntimeError("HTTP client not initialised (server not started)")
    return _http_client


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="MCP Server 1 — Numerical Data Pipeline",
    description="Tool server for price history, fundamentals, and macro data ingestion.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Pydantic request/response schemas ───────────────────────────────────────

class DateRangeRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


class TickerDateRequest(DateRangeRequest):
    ticker: str


class MacroRequest(DateRangeRequest):
    indicator_name: str
    fred_code: str


class RBIMacroRequest(DateRangeRequest):
    indicator_name: str


class ToolResponse(BaseModel):
    status: str
    data: dict[str, Any] | list | None = None
    error: str | None = None


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "server": "mcp_server_1", "version": "1.0.0"}


# ── Tool endpoints ───────────────────────────────────────────────────────────

@app.post("/tools/get_price_history")
async def ep_get_price_history(req: TickerDateRequest):
    from .tools import tool_get_price_history

    return await tool_get_price_history(
        ticker=req.ticker,
        start_date=req.start_date,
        end_date=req.end_date,
    )


@app.post("/tools/get_fundamentals")
async def ep_get_fundamentals(ticker: str = Query(...)):
    from .tools import tool_get_fundamentals

    return await tool_get_fundamentals(ticker=ticker)


@app.post("/tools/get_macro_indicator")
async def ep_get_macro_indicator(req: MacroRequest):
    from .tools import tool_get_macro_indicator

    return await tool_get_macro_indicator(
        fred_code=req.fred_code,
        start_date=req.start_date,
        end_date=req.end_date,
    )


@app.post("/tools/ingest_ticker_history")
async def ep_ingest_ticker_history(req: TickerDateRequest):
    from .tools import tool_ingest_ticker_history

    return await tool_ingest_ticker_history(
        ticker=req.ticker,
        start_date=req.start_date,
        end_date=req.end_date,
    )


@app.post("/tools/ingest_fundamentals")
async def ep_ingest_fundamentals(
    ticker: str = Query(...),
    period: str = Query("LATEST"),
):
    from .tools import tool_ingest_fundamentals

    return await tool_ingest_fundamentals(ticker=ticker, period=period)


@app.post("/tools/ingest_macro")
async def ep_ingest_macro(req: MacroRequest):
    from .tools import tool_ingest_macro

    return await tool_ingest_macro(
        indicator_name=req.indicator_name,
        fred_code=req.fred_code,
        start_date=req.start_date,
        end_date=req.end_date,
    )


@app.post("/tools/ingest_nse_bhavcopy")
async def ep_ingest_nse_bhavcopy(trade_date: str = Query(...)):
    from .tools import tool_ingest_nse_bhavcopy

    return await tool_ingest_nse_bhavcopy(trade_date=trade_date)


@app.post("/tools/ingest_rbi_macro")
async def ep_ingest_rbi_macro(req: RBIMacroRequest):
    from .tools import tool_ingest_rbi_macro

    return await tool_ingest_rbi_macro(
        indicator_name=req.indicator_name,
        start_date=req.start_date,
        end_date=req.end_date,
    )


@app.post("/tools/run_quality_checks")
async def ep_run_quality_checks(
    expected_ticker_count: int | None = Query(None),
):
    from .tools import tool_run_quality_checks

    return await tool_run_quality_checks(
        expected_ticker_count=expected_ticker_count,
    )


# ── Cache management ────────────────────────────────────────────────────────

@app.post("/cache/clear")
async def clear_cache():
    request_cache.clear()
    return {"status": "ok", "message": "Cache cleared"}

"""
MCP Server 1 — Tool definitions.

Each tool wraps an underlying Django-based service function and adds:
  - Request caching (TTL-based in-memory)
  - Rate limiting (per-source token bucket)
  - Structured response envelopes
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Any

from .cache import request_cache
from .config import get_settings
from .rate_limiter import rate_limiter

logger = logging.getLogger("mcp_server_1.tools")
settings = get_settings()


def _setup_django() -> None:
    """Ensure Django settings are loaded before accessing ORM."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings.DJANGO_SETTINGS_MODULE)
    import django

    django.setup()


# Initialise Django once at module import
_setup_django()

from apps.data_ingestion.services import (
    DataQualityCheck,
    MacroIngester,
    MarketDataIngester,
    NSEBhavcopyIngester,
    get_fundamentals,
    get_macro_indicator,
    get_price_history,
    log_ingestion,
)
from apps.portfolio.models import DataIngestionLog, Watchlist


# ── MCP Tool: get_price_history ──────────────────────────────────────────────

async def tool_get_price_history(
    ticker: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    MCP tool — fetch OHLCV price history for a single ticker.

    Args:
        ticker: Stock ticker (e.g. 'RELIANCE.NS' or 'TCS').
        start_date: ISO date string (YYYY-MM-DD).
        end_date: ISO date string (YYYY-MM-DD).

    Returns:
        Envelope with status, data rows, and metadata.
    """
    cache_key = f"price:{ticker}:{start_date}:{end_date}"
    cached = request_cache.get(cache_key)
    if cached is not None:
        return cached

    await rate_limiter.acquire("yfinance")

    try:
        sd = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
        rows = get_price_history(ticker=ticker, start_date=sd, end_date=ed)

        result = {
            "status": "success",
            "ticker": ticker,
            "rows": len(rows),
            "data": rows,
        }
        request_cache.set(cache_key, result, ttl=settings.CACHE_TTL_PRICE)
        return result

    except Exception as exc:
        logger.exception("tool_get_price_history failed for %s", ticker)
        return {"status": "error", "ticker": ticker, "error": str(exc)}


# ── MCP Tool: get_fundamentals ───────────────────────────────────────────────

async def tool_get_fundamentals(ticker: str) -> dict[str, Any]:
    """
    MCP tool — fetch fundamental data (revenue, EPS, PE, etc.) for a ticker.
    """
    cache_key = f"fundamentals:{ticker}"
    cached = request_cache.get(cache_key)
    if cached is not None:
        return cached

    await rate_limiter.acquire("yfinance")

    try:
        payload = get_fundamentals(ticker=ticker)
        result = {"status": "success", **payload}
        request_cache.set(cache_key, result, ttl=settings.CACHE_TTL_FUNDAMENTALS)
        return result

    except Exception as exc:
        logger.exception("tool_get_fundamentals failed for %s", ticker)
        return {"status": "error", "ticker": ticker, "error": str(exc)}


# ── MCP Tool: get_macro_indicator ────────────────────────────────────────────

async def tool_get_macro_indicator(
    fred_code: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    MCP tool — fetch FRED macro economic indicator series.
    """
    cache_key = f"macro:{fred_code}:{start_date}:{end_date}"
    cached = request_cache.get(cache_key)
    if cached is not None:
        return cached

    await rate_limiter.acquire("fred")

    try:
        sd = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
        rows = get_macro_indicator(fred_code=fred_code, start_date=sd, end_date=ed)

        result = {
            "status": "success",
            "indicator": fred_code,
            "rows": len(rows),
            "data": rows,
        }
        request_cache.set(cache_key, result, ttl=settings.CACHE_TTL_MACRO)
        return result

    except Exception as exc:
        logger.exception("tool_get_macro_indicator failed for %s", fred_code)
        return {"status": "error", "indicator": fred_code, "error": str(exc)}


# ── MCP Tool: ingest_ticker_history ──────────────────────────────────────────

async def tool_ingest_ticker_history(
    ticker: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    MCP tool — ingest OHLCV history into database for a ticker.
    """
    await rate_limiter.acquire("yfinance")

    try:
        sd = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = dt.datetime.strptime(end_date, "%Y-%m-%d").date()

        ingester = MarketDataIngester()
        written = ingester.ingest_ticker_history(
            ticker=ticker, start_date=sd, end_date=ed,
        )
        return {"status": "success", "ticker": ticker, "records_written": written}

    except Exception as exc:
        logger.exception("tool_ingest_ticker_history failed for %s", ticker)
        return {"status": "error", "ticker": ticker, "error": str(exc)}


# ── MCP Tool: ingest_fundamentals ────────────────────────────────────────────

async def tool_ingest_fundamentals(
    ticker: str,
    period: str = "LATEST",
) -> dict[str, Any]:
    """
    MCP tool — ingest fundamental data into database for a ticker.
    """
    await rate_limiter.acquire("yfinance")

    try:
        ingester = MarketDataIngester()
        obj = ingester.ingest_fundamentals(ticker=ticker, period=period)
        return {
            "status": "success",
            "ticker": ticker,
            "period": period,
            "id": obj.pk,
        }

    except Exception as exc:
        logger.exception("tool_ingest_fundamentals failed for %s", ticker)
        return {"status": "error", "ticker": ticker, "error": str(exc)}


# ── MCP Tool: ingest_macro ───────────────────────────────────────────────────

async def tool_ingest_macro(
    indicator_name: str,
    fred_code: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    MCP tool — ingest FRED macro indicator data into database.
    """
    await rate_limiter.acquire("fred")

    try:
        sd = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = dt.datetime.strptime(end_date, "%Y-%m-%d").date()

        ingester = MacroIngester()
        written = ingester.ingest_fred_indicator(
            indicator_name=indicator_name,
            fred_code=fred_code,
            start_date=sd,
            end_date=ed,
        )
        return {
            "status": "success",
            "indicator": indicator_name,
            "records_written": written,
        }

    except Exception as exc:
        logger.exception("tool_ingest_macro failed for %s", fred_code)
        return {"status": "error", "indicator": indicator_name, "error": str(exc)}


# ── MCP Tool: ingest_nse_bhavcopy ────────────────────────────────────────────

async def tool_ingest_nse_bhavcopy(trade_date: str) -> dict[str, Any]:
    """
    MCP tool — download and ingest NSE Bhavcopy for a given trade date.
    """
    await rate_limiter.acquire("nse")

    try:
        parsed_date = dt.datetime.strptime(trade_date, "%Y-%m-%d").date()
        ingester = NSEBhavcopyIngester()
        written = ingester.store_prices(parsed_date)
        return {
            "status": "success",
            "trade_date": trade_date,
            "records_written": written,
        }

    except Exception as exc:
        logger.exception("tool_ingest_nse_bhavcopy failed for %s", trade_date)
        return {"status": "error", "trade_date": trade_date, "error": str(exc)}


# ── MCP Tool: ingest_rbi_macro ───────────────────────────────────────────────

async def tool_ingest_rbi_macro(
    indicator_name: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    MCP tool — ingest RBI India macro data (repo rate, CPI, INR/USD).
    """
    await rate_limiter.acquire("rbi")

    try:
        from apps.data_ingestion.services import RBIDataIngester

        sd = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = dt.datetime.strptime(end_date, "%Y-%m-%d").date()

        ingester = RBIDataIngester()
        written = ingester.ingest_indicator(
            indicator_name=indicator_name, start_date=sd, end_date=ed,
        )
        return {
            "status": "success",
            "indicator": indicator_name,
            "records_written": written,
        }

    except Exception as exc:
        logger.exception("tool_ingest_rbi_macro failed for %s", indicator_name)
        return {"status": "error", "indicator": indicator_name, "error": str(exc)}


# ── MCP Tool: run_quality_checks ─────────────────────────────────────────────

async def tool_run_quality_checks(
    expected_ticker_count: int | None = None,
) -> dict[str, Any]:
    """
    MCP tool — run data quality checks across the pipeline.
    """
    try:
        quality = DataQualityCheck()
        tickers = list(
            Watchlist.objects.filter(is_active=True).values_list("ticker", flat=True)
        )

        per_ticker = [
            quality.validate_price_rows(ticker=t, lookback_days=7) for t in tickers
        ]
        coverage = quality.validate_expected_ticker_coverage(
            expected_count=expected_ticker_count
            if expected_ticker_count is not None
            else len(tickers)
        )
        gap_report = quality.detect_date_gaps(lookback_days=30)

        passed = (
            all(item["passed"] for item in per_ticker)
            and coverage["passed"]
        )
        return {
            "status": "success",
            "overall_passed": passed,
            "coverage": coverage,
            "per_ticker": per_ticker,
            "date_gaps": gap_report,
        }

    except Exception as exc:
        logger.exception("tool_run_quality_checks failed")
        return {"status": "error", "error": str(exc)}

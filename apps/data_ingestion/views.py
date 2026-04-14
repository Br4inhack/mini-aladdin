"""
Data Ingestion API Views — Person 2

Provides REST endpoints to:
  - Trigger ingestion tasks (price, fundamentals, macro, RBI, bhavcopy)
  - Check ingestion log / status
  - Run data quality checks
  - Inspect FII/DII flow data

All heavy work is dispatched to Celery; views return immediately with a task ID.
"""
from __future__ import annotations

import datetime as dt
import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.portfolio.models import (
    DataIngestionLog,
    FundamentalData,
    MacroIndicator,
    PriceHistory,
    Watchlist,
)
from .models import FIIDIIData
from .services import DataQualityCheck

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_date(value: str | None, default: dt.date) -> dt.date:
    if not value:
        return default
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default


# ── Health ────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health(request: Request) -> Response:
    """
    GET /api/data/health/
    Returns a simple liveness check with counts from the three core tables.
    """
    return Response(
        {
            "status": "ok",
            "price_records": PriceHistory.objects.count(),
            "fundamental_records": FundamentalData.objects.count(),
            "macro_records": MacroIndicator.objects.count(),
        }
    )


# ── Ingestion Log ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ingestion_log_list(request: Request) -> Response:
    """
    GET /api/data/logs/
    Returns the last 100 ingestion log entries, most recent first.

    Query params:
      ?source=yfinance       — filter by source_name
      ?status=FAILED         — filter by status (SUCCESS / PARTIAL / FAILED)
      ?ticker=RELIANCE       — filter by ticker
    """
    qs = DataIngestionLog.objects.all().order_by("-timestamp")

    source = request.query_params.get("source")
    if source:
        qs = qs.filter(source_name__icontains=source)

    ingestion_status = request.query_params.get("status")
    if ingestion_status:
        qs = qs.filter(status=ingestion_status.upper())

    ticker = request.query_params.get("ticker")
    if ticker:
        qs = qs.filter(ticker__icontains=ticker.upper())

    entries = qs[:100].values(
        "id",
        "source_name",
        "ticker",
        "status",
        "records_fetched",
        "error_message",
        "timestamp",
    )
    return Response({"count": len(list(entries)), "results": list(entries)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ingestion_log_summary(request: Request) -> Response:
    """
    GET /api/data/logs/summary/
    Aggregated counts by source and status for the last 24 hours.
    """
    since = timezone.now() - dt.timedelta(hours=24)
    logs = DataIngestionLog.objects.filter(timestamp__gte=since)

    by_source: dict[str, dict] = {}
    for log in logs:
        key = log.source_name
        if key not in by_source:
            by_source[key] = {"SUCCESS": 0, "PARTIAL": 0, "FAILED": 0, "records": 0}
        by_source[key][log.status] = by_source[key].get(log.status, 0) + 1
        by_source[key]["records"] += log.records_fetched

    return Response({"since": since.isoformat(), "by_source": by_source})


# ── Trigger: Price History ────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_price_ingestion(request: Request) -> Response:
    """
    POST /api/data/trigger/prices/
    Enqueue Celery task to ingest OHLCV history for all active watchlist tickers.

    Body (optional JSON):
      { "days": 365 }   — lookback window (default 1095 = 3 years)
    """
    from .tasks import ingest_watchlist_price_history_batch

    days = int(request.data.get("days", 365 * 3))
    task = ingest_watchlist_price_history_batch.delay(days=days)
    return Response(
        {
            "status": "queued",
            "task_id": task.id,
            "message": f"Price ingestion task queued for {days}-day lookback.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_ticker_price_ingestion(request: Request) -> Response:
    """
    POST /api/data/trigger/prices/<ticker>/
    Enqueue Celery task to ingest OHLCV history for a single ticker.

    Body (optional JSON):
      { "days": 365, "ticker": "RELIANCE" }
    """
    from .tasks import ingest_watchlist_price_history

    ticker = request.data.get("ticker") or request.query_params.get("ticker")
    if not ticker:
        return Response(
            {"error": "ticker is required"}, status=status.HTTP_400_BAD_REQUEST
        )

    # Validate ticker exists in watchlist
    if not Watchlist.objects.filter(ticker=ticker.upper(), is_active=True).exists():
        return Response(
            {"error": f"Ticker '{ticker}' not found in active watchlist."},
            status=status.HTTP_404_NOT_FOUND,
        )

    days = int(request.data.get("days", 365 * 3))
    task = ingest_watchlist_price_history.delay(days=days)
    return Response(
        {
            "status": "queued",
            "task_id": task.id,
            "ticker": ticker.upper(),
            "message": f"Price ingestion task queued for {ticker.upper()}.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


# ── Trigger: Fundamentals ─────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_fundamentals_ingestion(request: Request) -> Response:
    """
    POST /api/data/trigger/fundamentals/
    Enqueue Celery task to ingest fundamental data for all active tickers.

    Body (optional JSON):
      { "ticker": "TCS" }   — restrict to single ticker (optional)
    """
    from .tasks import ingest_fundamentals_all

    ticker = request.data.get("ticker")
    task = ingest_fundamentals_all.delay(ticker=ticker)
    return Response(
        {
            "status": "queued",
            "task_id": task.id,
            "message": "Fundamentals ingestion task queued.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


# ── Trigger: Macro / FRED ─────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_macro_ingestion(request: Request) -> Response:
    """
    POST /api/data/trigger/macro/
    Enqueue Celery task to ingest FRED and RBI macro indicators.

    Body (optional JSON):
      { "days": 365 }
    """
    from .tasks import ingest_rbi_macro_data

    days = int(request.data.get("days", 365 * 3))
    task = ingest_rbi_macro_data.delay(days=days)
    return Response(
        {
            "status": "queued",
            "task_id": task.id,
            "message": f"Macro (RBI) ingestion task queued for {days}-day lookback.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_fred_ingestion(request: Request) -> Response:
    """
    POST /api/data/trigger/fred/
    Enqueue Celery task for a single FRED indicator.

    Body (required JSON):
      { "indicator_name": "US_GDP", "fred_code": "GDP", "days": 365 }
    """
    from .tasks import ingest_fred_macro_indicator

    indicator_name = request.data.get("indicator_name")
    fred_code = request.data.get("fred_code")
    if not indicator_name or not fred_code:
        return Response(
            {"error": "Both 'indicator_name' and 'fred_code' are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    days = int(request.data.get("days", 365 * 3))
    task = ingest_fred_macro_indicator.delay(
        indicator_name=indicator_name, fred_code=fred_code, days=days
    )
    return Response(
        {
            "status": "queued",
            "task_id": task.id,
            "indicator": indicator_name,
            "fred_code": fred_code,
        },
        status=status.HTTP_202_ACCEPTED,
    )


# ── Trigger: NSE Bhavcopy ─────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_bhavcopy_ingestion(request: Request) -> Response:
    """
    POST /api/data/trigger/bhavcopy/
    Enqueue Celery task to download and parse NSE Bhavcopy for a given date.

    Body (optional JSON):
      { "trade_date": "2025-03-31" }   — defaults to yesterday
    """
    from .tasks import ingest_nse_bhavcopy_prices

    trade_date_str = request.data.get("trade_date")
    if not trade_date_str:
        yesterday = (timezone.now().date() - dt.timedelta(days=1)).isoformat()
        trade_date_str = yesterday

    # Basic date validation
    try:
        dt.datetime.strptime(trade_date_str, "%Y-%m-%d")
    except ValueError:
        return Response(
            {"error": "trade_date must be in YYYY-MM-DD format."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = ingest_nse_bhavcopy_prices.delay(trade_date=trade_date_str)
    return Response(
        {
            "status": "queued",
            "task_id": task.id,
            "trade_date": trade_date_str,
        },
        status=status.HTTP_202_ACCEPTED,
    )


# ── Data Quality ──────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def data_quality_report(request: Request) -> Response:
    """
    GET /api/data/quality/
    Run synchronous data quality checks and return a full report.

    Query params:
      ?expected=73         — expected ticker count (default: active watchlist count)
      ?lookback_days=7     — days to look back for per-ticker validation
    """
    expected = request.query_params.get("expected")
    lookback_days = int(request.query_params.get("lookback_days", 7))
    expected_count = int(expected) if expected else None

    checker = DataQualityCheck()
    tickers = list(
        Watchlist.objects.filter(is_active=True).values_list("ticker", flat=True)
    )

    per_ticker = [
        checker.validate_price_rows(ticker=t, lookback_days=lookback_days)
        for t in tickers
    ]
    coverage = checker.validate_expected_ticker_coverage(
        expected_count=expected_count if expected_count is not None else len(tickers)
    )
    gap_report = checker.detect_date_gaps(lookback_days=30)

    failed_tickers = [r for r in per_ticker if not r["passed"]]
    overall_passed = coverage["passed"] and len(failed_tickers) == 0

    return Response(
        {
            "overall_passed": overall_passed,
            "coverage": coverage,
            "failed_ticker_count": len(failed_tickers),
            "failed_tickers": failed_tickers,
            "date_gaps_found": len(gap_report),
            "date_gaps": gap_report,
            "per_ticker": per_ticker,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_quality_check(request: Request) -> Response:
    """
    POST /api/data/quality/trigger/
    Enqueue async data quality check task.
    """
    from .tasks import run_data_quality_checks

    expected = request.data.get("expected_ticker_count")
    task = run_data_quality_checks.delay(
        expected_ticker_count=int(expected) if expected else None
    )
    return Response(
        {"status": "queued", "task_id": task.id},
        status=status.HTTP_202_ACCEPTED,
    )


# ── Price History ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def price_history(request: Request) -> Response:
    """
    GET /api/data/prices/?ticker=RELIANCE&start=2025-01-01&end=2025-03-31
    Returns OHLCV rows from the DB for a given ticker and date range.
    """
    ticker = request.query_params.get("ticker", "").upper()
    if not ticker:
        return Response(
            {"error": "ticker query param is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    end_date = _parse_date(request.query_params.get("end"), timezone.now().date())
    start_date = _parse_date(
        request.query_params.get("start"),
        end_date - dt.timedelta(days=90),
    )

    rows = (
        PriceHistory.objects.filter(
            ticker__ticker=ticker,
            date__gte=start_date,
            date__lte=end_date,
        )
        .order_by("date")
        .values("date", "open", "high", "low", "close", "volume")
    )

    return Response(
        {
            "ticker": ticker,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "count": rows.count(),
            "rows": list(rows),
        }
    )


# ── Fundamentals ──────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fundamental_data(request: Request) -> Response:
    """
    GET /api/data/fundamentals/?ticker=TCS
    Returns fundamental data records for a given ticker.
    """
    ticker = request.query_params.get("ticker", "").upper()
    if not ticker:
        return Response(
            {"error": "ticker query param is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    rows = FundamentalData.objects.filter(ticker__ticker=ticker).order_by("-period").values(
        "period", "revenue", "eps", "debt_ratio", "roe", "pe_ratio",
        "net_margin", "promoter_pledge_pct", "updated_at",
    )
    return Response({"ticker": ticker, "count": rows.count(), "rows": list(rows)})


# ── Macro Indicators ──────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def macro_indicators(request: Request) -> Response:
    """
    GET /api/data/macro/
    Returns macro indicator values.

    Query params:
      ?indicator=repo_rate    — filter by indicator_name
      ?start=2024-01-01
      ?end=2025-01-01
    """
    indicator = request.query_params.get("indicator")
    end_date = _parse_date(request.query_params.get("end"), timezone.now().date())
    start_date = _parse_date(
        request.query_params.get("start"),
        end_date - dt.timedelta(days=365),
    )

    qs = MacroIndicator.objects.filter(date__gte=start_date, date__lte=end_date)
    if indicator:
        qs = qs.filter(indicator_name__icontains=indicator)

    rows = qs.order_by("indicator_name", "date").values(
        "indicator_name", "value", "date", "source"
    )
    return Response(
        {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "count": rows.count(),
            "rows": list(rows),
        }
    )


# ── FII / DII ─────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fii_dii_data(request: Request) -> Response:
    """
    GET /api/data/fii-dii/
    Returns FII/DII net flow data.

    Query params:
      ?start=2025-01-01
      ?end=2025-03-31
    """
    end_date = _parse_date(request.query_params.get("end"), timezone.now().date())
    start_date = _parse_date(
        request.query_params.get("start"),
        end_date - dt.timedelta(days=90),
    )

    rows = (
        FIIDIIData.objects.filter(date__gte=start_date, date__lte=end_date)
        .order_by("-date")
        .values("date", "fii_net_value", "dii_net_value", "source")
    )
    return Response(
        {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "count": rows.count(),
            "rows": list(rows),
        }
    )


# ── Watchlist Coverage ────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def watchlist_coverage(request: Request) -> Response:
    """
    GET /api/data/coverage/
    Shows which active tickers have price data and how many rows each has.
    Useful for monitoring ingestion pipeline completeness.
    """
    tickers = Watchlist.objects.filter(is_active=True).order_by("ticker")
    result = []
    for wl in tickers:
        count = PriceHistory.objects.filter(ticker=wl).count()
        latest = (
            PriceHistory.objects.filter(ticker=wl)
            .order_by("-date")
            .values_list("date", flat=True)
            .first()
        )
        result.append(
            {
                "ticker": wl.ticker,
                "company_name": wl.company_name,
                "sector": wl.sector,
                "price_rows": count,
                "latest_date": latest.isoformat() if latest else None,
                "has_data": count > 0,
            }
        )

    total = len(result)
    with_data = sum(1 for r in result if r["has_data"])
    return Response(
        {
            "total_tickers": total,
            "tickers_with_data": with_data,
            "coverage_pct": round(with_data / total * 100, 1) if total else 0,
            "tickers": result,
        }
    )

from __future__ import annotations

import datetime as dt
import logging

from celery import shared_task
from django.utils import timezone

from apps.portfolio.models import DataIngestionLog, Watchlist
from .services import (
    DataQualityCheck,
    MacroIngester,
    MarketDataIngester,
    NSEBhavcopyIngester,
    RBIDataIngester,
    log_ingestion,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_watchlist_price_history(self, days: int = 365 * 3) -> dict[str, int]:
    end_date = timezone.now().date()
    start_date = end_date - dt.timedelta(days=days)

    try:
        ingester = MarketDataIngester()
        return ingester.ingest_watchlist_history(start_date=start_date, end_date=end_date)
    except Exception as exc:
        log_ingestion(
            source_name='yfinance',
            status=DataIngestionLog.Status.FAILED,
            error_message=str(exc),
        )
        logger.exception('watchlist price ingestion failed')
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_watchlist_price_history_batch(
    self, days: int = 365 * 3, batch_size: int = 10,
) -> dict[str, int]:
    """Batch-download and ingest price history for all active tickers."""
    end_date = timezone.now().date()
    start_date = end_date - dt.timedelta(days=days)

    try:
        ingester = MarketDataIngester()
        return ingester.ingest_watchlist_history_batch(
            start_date=start_date, end_date=end_date, batch_size=batch_size,
        )
    except Exception as exc:
        log_ingestion(
            source_name='yfinance_batch',
            status=DataIngestionLog.Status.FAILED,
            error_message=str(exc),
        )
        logger.exception('batch watchlist price ingestion failed')
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_benchmark_history(self, days: int = 365 * 3) -> dict[str, int]:
    end_date = timezone.now().date()
    start_date = end_date - dt.timedelta(days=days)

    try:
        ingester = MarketDataIngester()
        return ingester.ingest_benchmark_history(start_date=start_date, end_date=end_date)
    except Exception as exc:
        log_ingestion(
            source_name='yfinance_benchmark',
            status=DataIngestionLog.Status.FAILED,
            error_message=str(exc),
        )
        logger.exception('benchmark price ingestion failed')
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_fred_macro_indicator(
    self,
    indicator_name: str,
    fred_code: str,
    days: int = 365 * 3,
) -> int:
    end_date = timezone.now().date()
    start_date = end_date - dt.timedelta(days=days)

    try:
        ingester = MacroIngester()
        return ingester.ingest_fred_indicator(
            indicator_name=indicator_name,
            fred_code=fred_code,
            start_date=start_date,
            end_date=end_date,
            source='fred',
        )
    except Exception as exc:
        log_ingestion(
            source_name=f'fred:{fred_code}',
            status=DataIngestionLog.Status.FAILED,
            error_message=str(exc),
        )
        logger.exception('macro ingestion failed for %s', fred_code)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def ingest_nse_bhavcopy_prices(self, trade_date: str) -> int:
    try:
        parsed_date = dt.datetime.strptime(trade_date, '%Y-%m-%d').date()
        ingester = NSEBhavcopyIngester()
        return ingester.store_prices(parsed_date)
    except Exception as exc:
        log_ingestion(
            source_name='nse_bhavcopy',
            status=DataIngestionLog.Status.FAILED,
            error_message=str(exc),
        )
        logger.exception('bhavcopy ingestion failed for %s', trade_date)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_rbi_macro_data(self, days: int = 365 * 3) -> dict[str, int]:
    """Ingest all RBI macro indicators (repo rate, CPI India, INR/USD)."""
    end_date = timezone.now().date()
    start_date = end_date - dt.timedelta(days=days)

    try:
        ingester = RBIDataIngester()
        return ingester.ingest_all_indicators(start_date=start_date, end_date=end_date)
    except Exception as exc:
        log_ingestion(
            source_name='rbi',
            status=DataIngestionLog.Status.FAILED,
            error_message=str(exc),
        )
        logger.exception('RBI macro ingestion failed')
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_rbi_single_indicator(
    self,
    indicator_name: str,
    days: int = 365 * 3,
) -> int:
    """Ingest a single RBI indicator."""
    end_date = timezone.now().date()
    start_date = end_date - dt.timedelta(days=days)

    try:
        ingester = RBIDataIngester()
        return ingester.ingest_indicator(
            indicator_name=indicator_name,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        log_ingestion(
            source_name=f'rbi:{indicator_name}',
            status=DataIngestionLog.Status.FAILED,
            error_message=str(exc),
        )
        logger.exception('RBI ingestion failed for %s', indicator_name)
        raise self.retry(exc=exc)


@shared_task
def run_data_quality_checks(expected_ticker_count: int | None = None) -> dict[str, object]:
    quality = DataQualityCheck()
    tickers = list(Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True))

    per_ticker = [quality.validate_price_rows(ticker=ticker, lookback_days=7) for ticker in tickers]
    coverage = quality.validate_expected_ticker_coverage(
        expected_count=expected_ticker_count if expected_ticker_count is not None else len(tickers)
    )
    gap_report = quality.detect_date_gaps(lookback_days=30)

    passed = all(item['passed'] for item in per_ticker) and coverage['passed']
    log_ingestion(
        source_name='data_quality_monitor',
        status=DataIngestionLog.Status.SUCCESS if passed else DataIngestionLog.Status.PARTIAL,
        records_fetched=len(per_ticker),
        error_message='' if passed else 'Data quality checks detected gaps',
    )

    return {
        'passed': passed,
        'coverage': coverage,
        'per_ticker': per_ticker,
        'date_gaps': gap_report,
    }

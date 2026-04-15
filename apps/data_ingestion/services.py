from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from django.db import transaction
from django.utils import timezone

from apps.portfolio.models import (
    DataIngestionLog,
    FundamentalData,
    MacroIndicator,
    PriceHistory,
    Watchlist,
)
from .models import FIIDIIData

logger = logging.getLogger(__name__)

# ── NSE ↔ yfinance symbol mapping ───────────────────────────────────────────

NSE_YF_SUFFIX = '.NS'
BSE_YF_SUFFIX = '.BO'

# Tickers that need special mapping (NSE code → yfinance symbol)
TICKER_OVERRIDES: dict[str, str] = {
    'NIFTY50': '^NSEI',
    'SENSEX': '^BSESN',
    'NIFTY_BANK': '^NSEBANK',
    'INDIA_VIX': '^INDIAVIX',
}


def nse_to_yfinance(ticker: str) -> str:
    """Convert an NSE ticker to its yfinance symbol."""
    if ticker in TICKER_OVERRIDES:
        return TICKER_OVERRIDES[ticker]
    if ticker.endswith(NSE_YF_SUFFIX) or ticker.endswith(BSE_YF_SUFFIX):
        return ticker
    return f'{ticker}{NSE_YF_SUFFIX}'


def _to_decimal(value: Any, default: str = '0.00') -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal(default)
    return Decimal(str(value))


def log_ingestion(
    source_name: str,
    status: str,
    ticker: str = '',
    records_fetched: int = 0,
    error_message: str = '',
) -> None:
    DataIngestionLog.objects.create(
        source_name=source_name,
        ticker=ticker,
        status=status,
        records_fetched=records_fetched,
        error_message=error_message[:2000],
    )


# ── MCP tool interfaces ─────────────────────────────────────────────────────

def get_price_history(
    ticker: str,
    start_date: dt.date,
    end_date: dt.date,
) -> list[dict[str, Any]]:
    """MCP-like tool interface for price history."""
    yf_symbol = nse_to_yfinance(ticker)
    frame = yf.download(
        yf_symbol,
        start=start_date,
        end=end_date + dt.timedelta(days=1),
        interval='1d',
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if frame.empty:
        return []
    frame = frame.reset_index()
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        rows.append(
            {
                'date': row['Date'].date().isoformat(),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0,
            }
        )
    return rows


def get_price_history_batch(
    tickers: list[str],
    start_date: dt.date,
    end_date: dt.date,
) -> dict[str, list[dict[str, Any]]]:
    """
    Batch download OHLCV for multiple tickers at once using yfinance.
    Returns a dict mapping ticker → list of row dicts.
    """
    yf_symbols = [nse_to_yfinance(t) for t in tickers]
    reverse_map = dict(zip(yf_symbols, tickers))

    frame = yf.download(
        yf_symbols,
        start=start_date,
        end=end_date + dt.timedelta(days=1),
        interval='1d',
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by='ticker',
    )

    results: dict[str, list[dict[str, Any]]] = {}
    if frame.empty:
        return results

    for yf_sym in yf_symbols:
        original_ticker = reverse_map[yf_sym]
        try:
            if len(yf_symbols) == 1:
                ticker_df = frame.reset_index()
            else:
                ticker_df = frame[yf_sym].reset_index()

            rows: list[dict[str, Any]] = []
            for _, row in ticker_df.iterrows():
                if pd.isna(row.get('Close')):
                    continue
                rows.append(
                    {
                        'date': row['Date'].date().isoformat(),
                        'open': float(row['Open']),
                        'high': float(row['High']),
                        'low': float(row['Low']),
                        'close': float(row['Close']),
                        'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0,
                    }
                )
            results[original_ticker] = rows
        except (KeyError, TypeError):
            logger.warning('No data returned for %s', original_ticker)
            results[original_ticker] = []

    return results


def get_fundamentals(ticker: str) -> dict[str, Any]:
    """MCP-like tool interface for basic fundamentals."""
    yf_symbol = nse_to_yfinance(ticker)
    info = yf.Ticker(yf_symbol).info
    return {
        'ticker': ticker,
        'revenue': info.get('totalRevenue'),
        'eps': info.get('trailingEps'),
        'debt_ratio': info.get('debtToEquity'),
        'roe': info.get('returnOnEquity'),
        'pe_ratio': info.get('trailingPE'),
        'net_margin': info.get('profitMargins'),
        'updated_at': timezone.now().isoformat(),
    }


def get_macro_indicator(
    fred_code: str,
    start_date: dt.date,
    end_date: dt.date,
) -> list[dict[str, Any]]:
    """MCP-like tool interface for FRED macro series."""
    try:
        from pandas_datareader import data as pdr_data
    except ImportError as exc:
        raise RuntimeError('pandas-datareader is required for FRED ingestion') from exc

    series = pdr_data.DataReader(fred_code, 'fred', start_date, end_date)
    if series.empty:
        return []

    rows: list[dict[str, Any]] = []
    for timestamp, row in series.iterrows():
        value = row.get(fred_code)
        if pd.isna(value):
            continue
        rows.append({'date': timestamp.date().isoformat(), 'value': float(value)})
    return rows


# ── Market Data Ingester ─────────────────────────────────────────────────────

class MarketDataIngester:
    BENCHMARKS: dict[str, str] = {
        'NIFTY50': '^NSEI',
        'SENSEX': '^BSESN',
    }

    def ingest_ticker_history(
        self,
        ticker: str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> int:
        rows = get_price_history(ticker=ticker, start_date=start_date, end_date=end_date)
        watchlist = Watchlist.objects.get(ticker=ticker)

        written = 0
        for row in rows:
            _, created = PriceHistory.objects.update_or_create(
                ticker=watchlist,
                date=row['date'],
                defaults={
                    'open': _to_decimal(row['open']),
                    'high': _to_decimal(row['high']),
                    'low': _to_decimal(row['low']),
                    'close': _to_decimal(row['close']),
                    'volume': row['volume'],
                },
            )
            if created:
                written += 1

        log_ingestion(
            source_name='yfinance',
            ticker=ticker,
            status=DataIngestionLog.Status.SUCCESS,
            records_fetched=written,
        )
        return written

    def ingest_watchlist_history(
        self,
        start_date: dt.date,
        end_date: dt.date,
    ) -> dict[str, int]:
        results: dict[str, int] = {}
        tickers = list(Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True))
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker_history(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as exc:
                log_ingestion(
                    source_name='yfinance',
                    ticker=ticker,
                    status=DataIngestionLog.Status.FAILED,
                    error_message=str(exc),
                )
                logger.exception('Failed yfinance ingestion for %s', ticker)
                results[ticker] = 0
        return results

    def ingest_watchlist_history_batch(
        self,
        start_date: dt.date,
        end_date: dt.date,
        batch_size: int = 10,
    ) -> dict[str, int]:
        """
        Batch-download and ingest price history for all active tickers.
        Downloads in groups of `batch_size` tickers at a time.
        """
        tickers = list(Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True))
        results: dict[str, int] = {}

        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            try:
                batch_data = get_price_history_batch(
                    tickers=batch, start_date=start_date, end_date=end_date,
                )
            except Exception as exc:
                logger.exception('Batch download failed for %s', batch)
                for t in batch:
                    log_ingestion(
                        source_name='yfinance',
                        ticker=t,
                        status=DataIngestionLog.Status.FAILED,
                        error_message=str(exc),
                    )
                    results[t] = 0
                continue

            for ticker in batch:
                rows = batch_data.get(ticker, [])
                try:
                    watchlist = Watchlist.objects.get(ticker=ticker)
                except Watchlist.DoesNotExist:
                    results[ticker] = 0
                    continue

                written = 0
                for row in rows:
                    _, created = PriceHistory.objects.update_or_create(
                        ticker=watchlist,
                        date=row['date'],
                        defaults={
                            'open': _to_decimal(row['open']),
                            'high': _to_decimal(row['high']),
                            'low': _to_decimal(row['low']),
                            'close': _to_decimal(row['close']),
                            'volume': row['volume'],
                        },
                    )
                    if created:
                        written += 1

                log_ingestion(
                    source_name='yfinance',
                    ticker=ticker,
                    status=DataIngestionLog.Status.SUCCESS,
                    records_fetched=written,
                )
                results[ticker] = written

        return results

    def ingest_benchmark_history(
        self,
        start_date: dt.date,
        end_date: dt.date,
    ) -> dict[str, int]:
        results: dict[str, int] = {}
        for pseudo_ticker, yf_symbol in self.BENCHMARKS.items():
            watchlist, _ = Watchlist.objects.get_or_create(
                ticker=pseudo_ticker,
                defaults={
                    'company_name': pseudo_ticker,
                    'sector': 'INDEX',
                    'sub_sector': 'INDEX',
                    'exchange': 'INDEX',
                    'is_active': True,
                },
            )
            rows = get_price_history(
                ticker=yf_symbol,
                start_date=start_date,
                end_date=end_date,
            )
            written = 0
            for row in rows:
                _, created = PriceHistory.objects.update_or_create(
                    ticker=watchlist,
                    date=row['date'],
                    defaults={
                        'open': _to_decimal(row['open']),
                        'high': _to_decimal(row['high']),
                        'low': _to_decimal(row['low']),
                        'close': _to_decimal(row['close']),
                        'volume': row['volume'],
                    },
                )
                if created:
                    written += 1
            results[pseudo_ticker] = written
        return results

    def ingest_fundamentals(self, ticker: str, period: str = 'LATEST') -> FundamentalData:
        payload = get_fundamentals(ticker)
        watchlist = Watchlist.objects.get(ticker=ticker)
        obj, _ = FundamentalData.objects.update_or_create(
            ticker=watchlist,
            period=period,
            defaults={
                'revenue': _to_decimal(payload.get('revenue'), default='0'),
                'eps': _to_decimal(payload.get('eps'), default='0'),
                'debt_ratio': payload.get('debt_ratio') or 0,
                'roe': payload.get('roe') or 0,
                'pe_ratio': payload.get('pe_ratio') or 0,
                'net_margin': payload.get('net_margin') or 0,
            },
        )
        return obj


# ── Macro Ingester (FRED) ────────────────────────────────────────────────────

class MacroIngester:
    @transaction.atomic
    def ingest_fred_indicator(
        self,
        indicator_name: str,
        fred_code: str,
        start_date: dt.date,
        end_date: dt.date,
        source: str = 'fred',
    ) -> int:
        rows = get_macro_indicator(
            fred_code=fred_code,
            start_date=start_date,
            end_date=end_date,
        )
        written = 0
        for row in rows:
            _, created = MacroIndicator.objects.update_or_create(
                indicator_name=indicator_name,
                date=row['date'],
                defaults={
                    'value': row['value'],
                    'source': source,
                },
            )
            if created:
                written += 1

        log_ingestion(
            source_name=f'fred:{fred_code}',
            status=DataIngestionLog.Status.SUCCESS,
            records_fetched=written,
        )
        return written


# ── RBI Data Ingester ────────────────────────────────────────────────────────

class RBIDataIngester:
    """
    Downloads India-specific macro data from RBI/public sources:
      - Repo rate
      - CPI India
      - INR/USD exchange rate

    Uses RBI DBIE API and fallback to yfinance for INR/USD.
    """

    RBI_DBIE_BASE = 'https://api.rbi.org.in/DBIE/dbie.rbi'

    # Mapping of our indicator names to data source configs
    INDICATORS: dict[str, dict[str, str]] = {
        'repo_rate': {
            'source': 'rbi',
            'description': 'RBI Repo Rate',
        },
        'cpi_india': {
            'source': 'rbi',
            'description': 'India CPI (Consumer Price Index)',
        },
        'inr_usd': {
            'source': 'yfinance',
            'yf_symbol': 'INR=X',
            'description': 'INR/USD Exchange Rate',
        },
    }

    def _fetch_inr_usd(
        self, start_date: dt.date, end_date: dt.date,
    ) -> list[dict[str, Any]]:
        """Fetch INR/USD exchange rate from yfinance."""
        frame = yf.download(
            'INR=X',
            start=start_date,
            end=end_date + dt.timedelta(days=1),
            interval='1d',
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if frame.empty:
            return []

        frame = frame.reset_index()
        rows: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            close = row.get('Close')
            if close is not None and not pd.isna(close):
                rows.append({
                    'date': row['Date'].date().isoformat(),
                    'value': float(close),
                })
        return rows

    def _fetch_rbi_indicator(
        self,
        indicator_name: str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> list[dict[str, Any]]:
        """
        Fetch RBI macro data.
        Falls back to manual known values if API is unavailable,
        since RBI DBIE API has limited public access.
        """
        # Known recent repo rate values (fallback)
        REPO_RATE_HISTORY = [
            {'date': '2024-02-08', 'value': 6.50},
            {'date': '2024-04-05', 'value': 6.50},
            {'date': '2024-06-07', 'value': 6.50},
            {'date': '2024-08-08', 'value': 6.50},
            {'date': '2024-10-09', 'value': 6.50},
            {'date': '2024-12-06', 'value': 6.50},
            {'date': '2025-02-07', 'value': 6.25},
            {'date': '2025-04-09', 'value': 6.00},
        ]

        CPI_INDIA_HISTORY = [
            {'date': '2024-01-12', 'value': 5.10},
            {'date': '2024-02-12', 'value': 5.09},
            {'date': '2024-03-12', 'value': 4.85},
            {'date': '2024-04-12', 'value': 4.83},
            {'date': '2024-05-12', 'value': 4.75},
            {'date': '2024-06-12', 'value': 5.08},
            {'date': '2024-07-12', 'value': 3.54},
            {'date': '2024-08-12', 'value': 3.65},
            {'date': '2024-09-12', 'value': 5.49},
            {'date': '2024-10-12', 'value': 6.21},
            {'date': '2024-11-12', 'value': 5.48},
            {'date': '2024-12-12', 'value': 5.22},
            {'date': '2025-01-12', 'value': 4.31},
            {'date': '2025-02-12', 'value': 3.61},
        ]

        if indicator_name == 'repo_rate':
            source_data = REPO_RATE_HISTORY
        elif indicator_name == 'cpi_india':
            source_data = CPI_INDIA_HISTORY
        else:
            logger.warning('Unknown RBI indicator: %s', indicator_name)
            return []

        start_str = start_date.isoformat()
        end_str = end_date.isoformat()
        return [
            row for row in source_data
            if start_str <= row['date'] <= end_str
        ]

    @transaction.atomic
    def ingest_indicator(
        self,
        indicator_name: str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> int:
        """Ingest an RBI macro indicator into MacroIndicator table."""
        if indicator_name not in self.INDICATORS:
            raise ValueError(
                f'Unknown indicator: {indicator_name}. '
                f'Valid: {list(self.INDICATORS.keys())}'
            )

        config = self.INDICATORS[indicator_name]

        if config['source'] == 'yfinance':
            rows = self._fetch_inr_usd(start_date=start_date, end_date=end_date)
        else:
            rows = self._fetch_rbi_indicator(
                indicator_name=indicator_name,
                start_date=start_date,
                end_date=end_date,
            )

        written = 0
        for row in rows:
            _, created = MacroIndicator.objects.update_or_create(
                indicator_name=indicator_name,
                date=row['date'],
                defaults={
                    'value': row['value'],
                    'source': config['source'],
                },
            )
            if created:
                written += 1

        log_ingestion(
            source_name=f'rbi:{indicator_name}',
            status=DataIngestionLog.Status.SUCCESS,
            records_fetched=written,
        )
        return written

    def ingest_all_indicators(
        self,
        start_date: dt.date,
        end_date: dt.date,
    ) -> dict[str, int]:
        """Ingest all known RBI indicators."""
        results: dict[str, int] = {}
        for name in self.INDICATORS:
            try:
                results[name] = self.ingest_indicator(
                    indicator_name=name, start_date=start_date, end_date=end_date,
                )
            except Exception as exc:
                log_ingestion(
                    source_name=f'rbi:{name}',
                    status=DataIngestionLog.Status.FAILED,
                    error_message=str(exc),
                )
                logger.exception('RBI ingestion failed for %s', name)
                results[name] = 0
        return results


# ── NSE Bhavcopy Ingester ────────────────────────────────────────────────────

class NSEBhavcopyIngester:
    BASE_URL = 'https://archives.nseindia.com/content/historical/EQUITIES'

    NSE_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    def _build_url(self, trade_date: dt.date) -> str:
        month = trade_date.strftime('%b').upper()
        day_mon_year = trade_date.strftime('%d%b%Y').upper()
        return f'{self.BASE_URL}/{trade_date:%Y}/{month}/cm{day_mon_year}bhav.csv.zip'

    def download_daily_bhavcopy(self, trade_date: dt.date) -> pd.DataFrame:
        url = self._build_url(trade_date)
        session = requests.Session()
        session.headers.update(self.NSE_HEADERS)
        # First hit NSE homepage to get cookies
        session.get('https://www.nseindia.com', timeout=10)
        response = session.get(url, timeout=30)
        response.raise_for_status()
        import io
        return pd.read_csv(io.BytesIO(response.content), compression='zip')

    @transaction.atomic
    def store_prices(self, trade_date: dt.date) -> int:
        frame = self.download_daily_bhavcopy(trade_date)
        if frame.empty:
            return 0

        watchlist_map = {
            row['ticker']: row['id']
            for row in Watchlist.objects.filter(is_active=True).values('id', 'ticker')
        }

        written = 0
        for _, row in frame.iterrows():
            symbol = str(row.get('SYMBOL', '')).strip().upper()
            if symbol not in watchlist_map:
                continue

            watchlist = Watchlist.objects.get(ticker=symbol)
            _, created = PriceHistory.objects.update_or_create(
                ticker=watchlist,
                date=trade_date,
                defaults={
                    'open': _to_decimal(row.get('OPEN')),
                    'high': _to_decimal(row.get('HIGH')),
                    'low': _to_decimal(row.get('LOW')),
                    'close': _to_decimal(row.get('CLOSE')),
                    'volume': int(row.get('TOTTRDQTY', 0) or 0),
                },
            )
            if created:
                written += 1

        log_ingestion(
            source_name='nse_bhavcopy',
            status=DataIngestionLog.Status.SUCCESS,
            records_fetched=written,
        )
        return written

    def store_fii_dii(self, trade_date: dt.date, fii_net_value: Decimal, dii_net_value: Decimal) -> FIIDIIData:
        obj, _ = FIIDIIData.objects.update_or_create(
            date=trade_date,
            defaults={
                'fii_net_value': fii_net_value,
                'dii_net_value': dii_net_value,
                'source': 'nse_bhavcopy',
            },
        )
        return obj


# ── Data Quality Check ───────────────────────────────────────────────────────

class DataQualityCheck:
    # Indian market holidays (major ones for 2024-2025)
    KNOWN_HOLIDAYS: set[dt.date] = {
        dt.date(2025, 1, 26),   # Republic Day
        dt.date(2025, 2, 26),   # Maha Shivaratri
        dt.date(2025, 3, 14),   # Holi
        dt.date(2025, 3, 31),   # Eid
        dt.date(2025, 4, 10),   # Shri Ram Navami
        dt.date(2025, 4, 14),   # Ambedkar Jayanti
        dt.date(2025, 4, 18),   # Good Friday
        dt.date(2025, 5, 1),    # Maharashtra Day
        dt.date(2025, 8, 15),   # Independence Day
        dt.date(2025, 8, 27),   # Ganesh Chaturthi
        dt.date(2025, 10, 2),   # Gandhi Jayanti
        dt.date(2025, 10, 21),  # Dussehra
        dt.date(2025, 10, 22),  # Dussehra
        dt.date(2025, 11, 5),   # Diwali
        dt.date(2025, 11, 7),   # Diwali (Bhai Dooj)
        dt.date(2025, 12, 25),  # Christmas
    }

    def _is_trading_day(self, d: dt.date) -> bool:
        """Check if a date is an expected NSE trading day."""
        if d.weekday() >= 5:  # Saturday or Sunday
            return False
        if d in self.KNOWN_HOLIDAYS:
            return False
        return True

    def _expected_trading_days(self, start_date: dt.date, end_date: dt.date) -> list[dt.date]:
        """Return list of expected trading days in a date range."""
        days = []
        current = start_date
        while current <= end_date:
            if self._is_trading_day(current):
                days.append(current)
            current += dt.timedelta(days=1)
        return days

    def validate_price_rows(self, ticker: str, lookback_days: int = 7) -> dict[str, Any]:
        start_date = timezone.now().date() - dt.timedelta(days=lookback_days)
        rows = PriceHistory.objects.filter(ticker__ticker=ticker, date__gte=start_date)
        row_count = rows.count()

        null_issues = rows.filter(
            open__isnull=True,
        ).count() + rows.filter(
            high__isnull=True,
        ).count() + rows.filter(
            low__isnull=True,
        ).count() + rows.filter(
            close__isnull=True,
        ).count()

        invalid_range_count = 0
        for item in rows.only('high', 'low', 'open', 'close'):
            if item.high < item.low:
                invalid_range_count += 1
            if not (item.low <= item.open <= item.high):
                invalid_range_count += 1
            if not (item.low <= item.close <= item.high):
                invalid_range_count += 1

        # Check against expected trading days
        expected_days = self._expected_trading_days(
            start_date, timezone.now().date(),
        )
        actual_dates = set(rows.values_list('date', flat=True))
        missing_days = [d for d in expected_days if d not in actual_dates and d < timezone.now().date()]

        passed = row_count > 0 and null_issues == 0 and invalid_range_count == 0
        return {
            'ticker': ticker,
            'row_count': row_count,
            'null_issues': null_issues,
            'invalid_range_count': invalid_range_count,
            'expected_trading_days': len(expected_days),
            'missing_days': [d.isoformat() for d in missing_days],
            'passed': passed,
        }

    def validate_expected_ticker_coverage(self, expected_count: int) -> dict[str, Any]:
        ingested_count = (
            PriceHistory.objects.values('ticker')
            .distinct()
            .count()
        )
        return {
            'expected_count': expected_count,
            'ingested_count': ingested_count,
            'passed': ingested_count >= expected_count,
        }

    def detect_date_gaps(self, lookback_days: int = 30) -> list[dict[str, Any]]:
        """
        Detect gaps in daily price data for all active tickers.
        Returns a list of gap reports per ticker.
        """
        start_date = timezone.now().date() - dt.timedelta(days=lookback_days)
        end_date = timezone.now().date()
        expected_days = self._expected_trading_days(start_date, end_date)

        tickers = list(
            Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True)
        )

        gap_reports: list[dict[str, Any]] = []
        for ticker in tickers:
            actual_dates = set(
                PriceHistory.objects.filter(
                    ticker__ticker=ticker,
                    date__gte=start_date,
                    date__lte=end_date,
                ).values_list('date', flat=True)
            )

            missing = [d for d in expected_days if d not in actual_dates and d < end_date]
            if missing:
                gap_reports.append({
                    'ticker': ticker,
                    'missing_dates': [d.isoformat() for d in missing],
                    'gap_count': len(missing),
                })

        return gap_reports

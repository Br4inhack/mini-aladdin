"""
Unit tests for apps/data_ingestion — Person 2

Tests cover:
  - Service layer (MarketDataIngester, DataQualityCheck)
  - Celery task wiring
  - API view endpoints (price history, logs, quality, triggers)

Uses Django TestCase with mock patches to avoid live API calls.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.portfolio.models import (
    DataIngestionLog,
    FundamentalData,
    MacroIndicator,
    PriceHistory,
    Watchlist,
)
from apps.data_ingestion.models import FIIDIIData
from apps.data_ingestion.services import (
    DataQualityCheck,
    MarketDataIngester,
    _to_decimal,
    nse_to_yfinance,
)

User = get_user_model()


# ── Helper fixtures ──────────────────────────────────────────────────────────

def make_watchlist(ticker: str = 'RELIANCE', sector: str = 'Energy') -> Watchlist:
    wl, _ = Watchlist.objects.get_or_create(
        ticker=ticker,
        defaults={
            'company_name': f'{ticker} Ltd',
            'sector': sector,
            'exchange': 'NSE',
            'is_active': True,
        },
    )
    return wl


def make_price_rows(wl: Watchlist, days: int = 5) -> list[PriceHistory]:
    rows = []
    base = dt.date(2025, 3, 1)
    for i in range(days):
        d = base + dt.timedelta(days=i)
        if d.weekday() < 5:  # skip weekends
            row, _ = PriceHistory.objects.get_or_create(
                ticker=wl,
                date=d,
                defaults={
                    'open': Decimal('100.00'),
                    'high': Decimal('105.00'),
                    'low': Decimal('98.00'),
                    'close': Decimal('102.00'),
                    'volume': 1_000_000,
                },
            )
            rows.append(row)
    return rows


# ── Service: helpers ─────────────────────────────────────────────────────────

class TestNseToYfinance(TestCase):
    def test_plain_ticker_gets_ns_suffix(self):
        self.assertEqual(nse_to_yfinance('RELIANCE'), 'RELIANCE.NS')

    def test_already_suffixed_ticker_unchanged(self):
        self.assertEqual(nse_to_yfinance('TCS.NS'), 'TCS.NS')

    def test_override_tickers_mapped_correctly(self):
        self.assertEqual(nse_to_yfinance('NIFTY50'), '^NSEI')
        self.assertEqual(nse_to_yfinance('SENSEX'), '^BSESN')

    def test_bse_suffix_unchanged(self):
        self.assertEqual(nse_to_yfinance('HDFC.BO'), 'HDFC.BO')


class TestToDecimal(TestCase):
    def test_none_returns_default(self):
        self.assertEqual(_to_decimal(None), Decimal('0.00'))

    def test_float_nan_returns_default(self):
        import math
        self.assertEqual(_to_decimal(float('nan')), Decimal('0.00'))

    def test_valid_float_converted(self):
        self.assertEqual(_to_decimal(123.45), Decimal('123.45'))

    def test_string_converted(self):
        self.assertEqual(_to_decimal('99.99'), Decimal('99.99'))


# ── Service: MarketDataIngester ───────────────────────────────────────────────

class TestMarketDataIngester(TestCase):

    def setUp(self):
        self.wl = make_watchlist('TCS', 'IT')
        self.ingester = MarketDataIngester()

    @patch('apps.data_ingestion.services.yf.download')
    def test_ingest_ticker_history_writes_price_rows(self, mock_download):
        """Ingester should create PriceHistory rows from yfinance data."""
        import pandas as pd

        mock_df = pd.DataFrame({
            'Date': pd.to_datetime(['2025-03-03', '2025-03-04']),
            'Open': [3400.0, 3420.0],
            'High': [3450.0, 3460.0],
            'Low':  [3390.0, 3410.0],
            'Close': [3440.0, 3450.0],
            'Volume': [500000, 600000],
        })
        mock_download.return_value = mock_df

        result = self.ingester.ingest_ticker_history(
            ticker='TCS',
            start_date=dt.date(2025, 3, 3),
            end_date=dt.date(2025, 3, 4),
        )
        self.assertGreaterEqual(result, 2)
        self.assertEqual(PriceHistory.objects.filter(ticker=self.wl).count(), 2)

    @patch('apps.data_ingestion.services.yf.Ticker')
    def test_ingest_fundamentals_writes_record(self, mock_ticker_cls):
        """Ingester should create/update a FundamentalData record."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            'totalRevenue': 2_000_000_000,
            'trailingEps': 120.5,
            'debtToEquity': 0.15,
            'returnOnEquity': 0.22,
            'trailingPE': 28.5,
            'profitMargins': 0.18,
        }
        mock_ticker_cls.return_value = mock_ticker

        obj = self.ingester.ingest_fundamentals(ticker='TCS', period='LATEST')
        self.assertIsInstance(obj, FundamentalData)
        self.assertEqual(obj.period, 'LATEST')
        self.assertAlmostEqual(float(obj.eps), 120.5, places=1)


# ── Service: DataQualityCheck ─────────────────────────────────────────────────

class TestDataQualityCheck(TestCase):

    def setUp(self):
        self.wl = make_watchlist('INFY', 'IT')
        self.checker = DataQualityCheck()

    def test_validate_price_rows_no_data(self):
        result = self.checker.validate_price_rows(ticker='INFY', lookback_days=7)
        self.assertFalse(result['passed'])
        self.assertEqual(result['row_count'], 0)

    def test_validate_price_rows_good_data(self):
        make_price_rows(self.wl, days=5)
        result = self.checker.validate_price_rows(ticker='INFY', lookback_days=30)
        # Should detect rows exist (may still flag missing recent days depending on
        # test run date vs holiday calendar — just check it returns a dict)
        self.assertIn('row_count', result)
        self.assertGreater(result['row_count'], 0)

    def test_validate_coverage_passes_when_enough_tickers(self):
        make_watchlist('WIPRO', 'IT')
        result = self.checker.validate_expected_ticker_coverage(expected_count=1)
        self.assertTrue(result['passed'])

    def test_validate_coverage_fails_when_not_enough_tickers(self):
        result = self.checker.validate_expected_ticker_coverage(expected_count=9999)
        self.assertFalse(result['passed'])

    def test_detect_date_gaps_returns_list(self):
        result = self.checker.detect_date_gaps(lookback_days=7)
        self.assertIsInstance(result, list)


# ── Model: FIIDIIData ─────────────────────────────────────────────────────────

class TestFIIDIIData(TestCase):

    def test_create_and_str(self):
        obj = FIIDIIData.objects.create(
            date=dt.date(2025, 3, 3),
            fii_net_value=Decimal('1234567.89'),
            dii_net_value=Decimal('-456789.01'),
            source='nse_bhavcopy',
        )
        self.assertIn('2025-03-03', str(obj))
        self.assertIn('1234567', str(obj))


# ── API Views ─────────────────────────────────────────────────────────────────

class DataIngestionAPITestBase(TestCase):
    """Base class for API tests — sets up auth and client."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', password='testpass123'
        )
        self.client.force_authenticate(user=self.user)


class TestHealthView(DataIngestionAPITestBase):

    def test_health_returns_200(self):
        resp = self.client.get('/api/data/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'ok')
        self.assertIn('price_records', resp.data)


class TestIngestionLogViews(DataIngestionAPITestBase):

    def setUp(self):
        super().setUp()
        DataIngestionLog.objects.create(
            source_name='yfinance',
            ticker='RELIANCE',
            status='SUCCESS',
            records_fetched=100,
        )

    def test_log_list_returns_entries(self):
        resp = self.client.get('/api/data/logs/')
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data['count'], 1)

    def test_log_list_filter_by_source(self):
        resp = self.client.get('/api/data/logs/?source=yfinance')
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data['count'], 1)

    def test_log_list_filter_by_status(self):
        resp = self.client.get('/api/data/logs/?status=FAILED')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 0)

    def test_log_summary_returns_by_source(self):
        resp = self.client.get('/api/data/logs/summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('by_source', resp.data)


class TestPriceHistoryView(DataIngestionAPITestBase):

    def setUp(self):
        super().setUp()
        self.wl = make_watchlist('HDFC', 'Banking')
        make_price_rows(self.wl, days=5)

    def test_price_history_requires_ticker(self):
        resp = self.client.get('/api/data/prices/')
        self.assertEqual(resp.status_code, 400)

    def test_price_history_returns_rows(self):
        resp = self.client.get('/api/data/prices/?ticker=HDFC&start=2025-02-01&end=2025-03-31')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('rows', resp.data)


class TestWatchlistCoverageView(DataIngestionAPITestBase):

    def setUp(self):
        super().setUp()
        wl = make_watchlist('BAJAJ', 'Finance')
        make_price_rows(wl, days=3)

    def test_coverage_shows_tickers(self):
        resp = self.client.get('/api/data/coverage/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('tickers_with_data', resp.data)
        self.assertGreaterEqual(resp.data['tickers_with_data'], 1)


class TestTriggerViews(DataIngestionAPITestBase):

    @patch('apps.data_ingestion.tasks.ingest_watchlist_price_history_batch.delay')
    def test_trigger_prices_returns_202(self, mock_delay):
        mock_delay.return_value = MagicMock(id='fake-task-id')
        resp = self.client.post('/api/data/trigger/prices/', {'days': 365}, format='json')
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data['status'], 'queued')
        self.assertIn('task_id', resp.data)

    @patch('apps.data_ingestion.tasks.ingest_rbi_macro_data.delay')
    def test_trigger_macro_returns_202(self, mock_delay):
        mock_delay.return_value = MagicMock(id='fake-task-id-2')
        resp = self.client.post('/api/data/trigger/macro/', {'days': 365}, format='json')
        self.assertEqual(resp.status_code, 202)

    def test_trigger_fred_requires_params(self):
        resp = self.client.post('/api/data/trigger/fred/', {}, format='json')
        self.assertEqual(resp.status_code, 400)

    @patch('apps.data_ingestion.tasks.ingest_fred_macro_indicator.delay')
    def test_trigger_fred_with_params_returns_202(self, mock_delay):
        mock_delay.return_value = MagicMock(id='fake-task-id-3')
        resp = self.client.post(
            '/api/data/trigger/fred/',
            {'indicator_name': 'US_GDP', 'fred_code': 'GDP'},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)

    def test_trigger_bhavcopy_invalid_date_returns_400(self):
        resp = self.client.post(
            '/api/data/trigger/bhavcopy/',
            {'trade_date': 'not-a-date'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    @patch('apps.data_ingestion.tasks.ingest_nse_bhavcopy_prices.delay')
    def test_trigger_bhavcopy_valid_date_returns_202(self, mock_delay):
        mock_delay.return_value = MagicMock(id='fake-task-id-4')
        resp = self.client.post(
            '/api/data/trigger/bhavcopy/',
            {'trade_date': '2025-03-31'},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)


class TestDataQualityView(DataIngestionAPITestBase):

    def test_quality_report_returns_200(self):
        resp = self.client.get('/api/data/quality/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('overall_passed', resp.data)
        self.assertIn('coverage', resp.data)

    @patch('apps.data_ingestion.tasks.run_data_quality_checks.delay')
    def test_quality_trigger_returns_202(self, mock_delay):
        mock_delay.return_value = MagicMock(id='fake-qc-task-id')
        resp = self.client.post('/api/data/quality/trigger/', {}, format='json')
        self.assertEqual(resp.status_code, 202)


class TestFIIDIIView(DataIngestionAPITestBase):

    def setUp(self):
        super().setUp()
        FIIDIIData.objects.create(
            date=dt.date(2025, 3, 3),
            fii_net_value=Decimal('5000000'),
            dii_net_value=Decimal('-2000000'),
        )

    def test_fii_dii_returns_rows(self):
        resp = self.client.get('/api/data/fii-dii/?start=2025-01-01&end=2025-12-31')
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data['count'], 1)


class TestMacroIndicatorsView(DataIngestionAPITestBase):

    def setUp(self):
        super().setUp()
        MacroIndicator.objects.create(
            indicator_name='repo_rate',
            value=6.50,
            date=dt.date(2025, 2, 7),
            source='rbi',
        )

    def test_macro_returns_rows(self):
        resp = self.client.get('/api/data/macro/?indicator=repo_rate')
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data['count'], 1)

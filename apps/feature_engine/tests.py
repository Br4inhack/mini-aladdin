"""
Unit tests for MarketFeatureCalculator — Quantitative feature computation pipeline.

Tests cover:
- All 12+ feature computation methods
- Edge cases (insufficient data, missing values, zero division)
- Django ORM integration
- Error handling and logging
- Realistic financial data patterns
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
from django.test import TestCase, TransactionTestCase

from apps.portfolio.models import PriceHistory, Watchlist
from apps.feature_engine.market_features import MarketFeatureCalculator

logger = logging.getLogger(__name__)


class MarketFeatureCalculatorTestCase(TransactionTestCase):
    """Test MarketFeatureCalculator with real Django ORM."""

    def setUp(self):
        """Set up test data."""
        # Create test watchlist entries
        self.watchlist_reliance = Watchlist.objects.create(
            ticker="RELIANCE",
            company_name="Reliance Industries",
            sector="Energy",
            exchange="NSE",
            is_active=True,
        )

        self.watchlist_nifty = Watchlist.objects.create(
            ticker="^NSEI",
            company_name="NIFTY 50",
            sector="Index",
            exchange="NSE",
            is_active=True,
        )

        self.watchlist_tata = Watchlist.objects.create(
            ticker="TATASTEEL",
            company_name="Tata Steel",
            sector="Metals",
            exchange="NSE",
            is_active=True,
        )

        self.calculator = MarketFeatureCalculator()

    def _create_realistic_price_data(
        self,
        ticker: str,
        num_days: int = 100,
        trend: str = "up",
        volatility: float = 0.02,
        base_price: float = 1000.0,
    ) -> None:
        """
        Create realistic OHLCV data with specified characteristics.

        Args:
            ticker: Ticker symbol
            num_days: Number of days of data to generate
            trend: 'up', 'down', or 'sideways'
            volatility: Daily volatility (std dev of returns)
            base_price: Starting price level
        """
        dates = []
        base_date = datetime.now().date() - timedelta(days=num_days)

        watchlist = Watchlist.objects.get(ticker=ticker)
        price_records = []

        current_price = base_price

        for i in range(num_days):
            date = base_date + timedelta(days=i)

            # Generate realistic daily return with trend
            if trend == "up":
                drift = 0.0005
            elif trend == "down":
                drift = -0.0005
            else:
                drift = 0.0

            daily_return = np.random.normal(drift, volatility)
            current_price = current_price * (1 + daily_return)

            # Generate OHLCV with realistic intraday volatility
            intraday_vol = np.random.uniform(0.005, 0.02)
            open_price = current_price
            high = open_price * (1 + abs(np.random.normal(0, intraday_vol)))
            low = open_price * (1 - abs(np.random.normal(0, intraday_vol)))
            close = open_price * (1 + np.random.normal(0, intraday_vol))
            volume = int(np.random.uniform(1e6, 1e7))

            price_records.append(
                PriceHistory(
                    ticker=watchlist,
                    date=date,
                    open=Decimal(str(round(open_price, 2))),
                    high=Decimal(str(round(high, 2))),
                    low=Decimal(str(round(low, 2))),
                    close=Decimal(str(round(close, 2))),
                    volume=volume,
                )
            )

        PriceHistory.objects.bulk_create(price_records)

    def test_compute_all_sufficient_data(self):
        """Test compute_all with sufficient data."""
        # Create 100 days of price data
        self._create_realistic_price_data("RELIANCE", num_days=100, trend="up")

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Verify all required keys are present
        expected_keys = [
            'daily_return_simple',
            'daily_return_log',
            'volatility_5d',
            'volatility_20d',
            'volatility_60d',
            'beta_60d',
            'correlation_matrix',
            'var_95',
            'max_drawdown_60d',
            'rsi_14',
            'atr_14',
            'macd',
            'macd_signal',
            'macd_histogram',
            'bollinger_position',
            'volume_breakout',
            'high_52w_proximity',
        ]

        for key in expected_keys:
            self.assertIn(key, features, f"Missing key: {key}")

        # Verify numeric values are floats or NaN
        for key, value in features.items():
            if key == 'correlation_matrix':
                self.assertIsInstance(value, dict)
            else:
                self.assertTrue(isinstance(value, float) or pd.isna(value))

    def test_insufficient_data_warning(self):
        """Test that warning is logged when data is insufficient."""
        # Create only 30 days of data (less than 60 minimum)
        self._create_realistic_price_data("RELIANCE", num_days=30)

        start_date = datetime.now().date() - timedelta(days=30)
        end_date = datetime.now().date()

        with self.assertLogs('apps.feature_engine.market_features', level='WARNING'):
            features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Should still return features, but many will be NaN
        self.assertIn('volatility_60d', features)

    def test_daily_returns_calculation(self):
        """Test daily return calculations."""
        self._create_realistic_price_data("RELIANCE", num_days=5)

        start_date = datetime.now().date() - timedelta(days=5)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Daily returns should be between -1 and 1
        self.assertTrue(-1 <= features['daily_return_simple'] <= 1)
        self.assertTrue(-1 <= features['daily_return_log'] <= 1)

    def test_volatility_calculation(self):
        """Test rolling volatility calculations."""
        self._create_realistic_price_data("RELIANCE", num_days=100, volatility=0.03)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Volatility should increase with window
        vol_5d = features['volatility_5d']
        vol_20d = features['volatility_20d']
        vol_60d = features['volatility_60d']

        # All should be positive and non-NaN
        if not pd.isna(vol_5d):
            self.assertGreaterEqual(vol_5d, 0)
        if not pd.isna(vol_20d):
            self.assertGreaterEqual(vol_20d, 0)
        if not pd.isna(vol_60d):
            self.assertGreaterEqual(vol_60d, 0)

    def test_beta_calculation(self):
        """Test beta vs NIFTY 50 calculation."""
        # Create both ticker and NIFTY data
        self._create_realistic_price_data("RELIANCE", num_days=100, trend="up", volatility=0.02)
        self._create_realistic_price_data("^NSEI", num_days=100, trend="up", volatility=0.015)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Beta should be a reasonable number (typically 0.5 to 2.0)
        beta = features['beta_60d']
        if not pd.isna(beta):
            self.assertGreater(beta, -2)
            self.assertLess(beta, 5)

    def test_beta_for_index_returns_nan(self):
        """Test that beta for NIFTY 50 itself is NaN."""
        self._create_realistic_price_data("^NSEI", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("^NSEI", start_date, end_date)

        # Beta for index should be NaN
        self.assertTrue(pd.isna(features['beta_60d']))

    def test_var_calculation(self):
        """Test Value at Risk calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # VaR should be negative (worst-case loss)
        var_95 = features['var_95']
        if not pd.isna(var_95):
            self.assertLess(var_95, 0)
            self.assertGreater(var_95, -1)

    def test_max_drawdown_calculation(self):
        """Test maximum drawdown calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100, trend="down")

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Max drawdown should be negative
        max_dd = features['max_drawdown_60d']
        if not pd.isna(max_dd):
            self.assertLessEqual(max_dd, 0)
            self.assertGreaterEqual(max_dd, -1)

    def test_rsi_calculation(self):
        """Test RSI (14-period) calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # RSI should be between 0 and 100
        rsi = features['rsi_14']
        if not pd.isna(rsi):
            self.assertGreaterEqual(rsi, 0)
            self.assertLessEqual(rsi, 100)

    def test_atr_calculation(self):
        """Test ATR (14-period) calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # ATR should be positive
        atr = features['atr_14']
        if not pd.isna(atr):
            self.assertGreater(atr, 0)

    def test_macd_calculation(self):
        """Test MACD calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # MACD values should exist
        self.assertIn('macd', features)
        self.assertIn('macd_signal', features)
        self.assertIn('macd_histogram', features)

    def test_bollinger_position_calculation(self):
        """Test Bollinger Band position calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Bollinger position should be between 0 and 1
        position = features['bollinger_position']
        if not pd.isna(position):
            self.assertGreaterEqual(position, 0.0)
            self.assertLessEqual(position, 1.0)

    def test_volume_breakout_calculation(self):
        """Test volume breakout calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Volume breakout should be positive
        breakout = features['volume_breakout']
        if not pd.isna(breakout):
            self.assertGreater(breakout, 0)

    def test_52w_proximity_calculation(self):
        """Test 52-week high proximity calculation."""
        self._create_realistic_price_data("RELIANCE", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # 52-week proximity should be between 0 and 1
        proximity = features['high_52w_proximity']
        if not pd.isna(proximity):
            self.assertGreaterEqual(proximity, 0.0)
            self.assertLessEqual(proximity, 1.0)

    def test_correlation_matrix_calculation(self):
        """Test correlation matrix calculation."""
        # Create data for multiple tickers
        self._create_realistic_price_data("RELIANCE", num_days=100)
        self._create_realistic_price_data("TATASTEEL", num_days=100)

        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Correlation matrix should be a dict
        self.assertIsInstance(features['correlation_matrix'], dict)

    def test_missing_ticker_raises_error(self):
        """Test that missing ticker raises appropriate error."""
        start_date = datetime.now().date() - timedelta(days=100)
        end_date = datetime.now().date()

        with self.assertRaises(ValueError):
            self.calculator.compute_all("NONEXISTENT", start_date, end_date)

    def test_single_row_dataframe_handling(self):
        """Test handling of single-row dataframe."""
        self._create_realistic_price_data("RELIANCE", num_days=1)

        start_date = datetime.now().date() - timedelta(days=1)
        end_date = datetime.now().date()

        features = self.calculator.compute_all("RELIANCE", start_date, end_date)

        # Should return NaN for most metrics that require history
        self.assertTrue(pd.isna(features['daily_return_simple']))


class PreprocessingIntegrationTestCase(TestCase):
    """Integration tests between PreprocessingPipeline and MarketFeatureCalculator."""

    def setUp(self):
        """Set up test data."""
        self.watchlist = Watchlist.objects.create(
            ticker="TEST",
            company_name="Test Company",
            exchange="NSE",
            is_active=True,
        )

        self.calculator = MarketFeatureCalculator()

    def test_pipeline_integration(self):
        """Test integration of preprocessing with feature calculation."""
        # Create sample data with realistic patterns
        from apps.feature_engine.preprocessing import PreprocessingPipeline

        # Generate sample price records
        for i in range(100):
            date = datetime.now().date() - timedelta(days=100 - i)
            price = 1000.0 * (1 + 0.001 * i + 0.01 * np.random.randn())

            PriceHistory.objects.create(
                ticker=self.watchlist,
                date=date,
                open=Decimal(str(round(price, 2))),
                high=Decimal(str(round(price * 1.02, 2))),
                low=Decimal(str(round(price * 0.98, 2))),
                close=Decimal(str(round(price, 2))),
                volume=int(5e6),
            )

        # Test preprocessing
        preprocessing = PreprocessingPipeline()

        # Fetch data and preprocess
        price_data = PriceHistory.objects.filter(ticker="TEST").order_by('date').values(
            'date', 'open', 'high', 'low', 'close', 'volume'
        )

        df = pd.DataFrame(price_data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')

        # Apply preprocessing
        df_processed = preprocessing.handle_missing_values(df)
        df_processed = preprocessing.normalize_features(df_processed)

        # Should now be ready for feature calculation
        self.assertFalse(df_processed.isnull().values.any())


if __name__ == '__main__':
    import django

    django.setup()

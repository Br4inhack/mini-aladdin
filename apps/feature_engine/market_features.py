"""
MarketFeatureCalculator — Computes quantitative market risk indicators for financial instruments.

This module provides a high-performance feature computation pipeline for OHLCV data,
including technical indicators, risk metrics, and correlation analysis integrated with
the Django ORM.

Key Features:
- 12+ technical and risk indicators
- Rolling window calculations (5d, 20d, 60d)
- Beta vs NIFTY 50 (market index)
- VaR 95% calculation (historical simulation)
- Comprehensive error handling for edge cases
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta

from apps.portfolio.models import PriceHistory, Watchlist

logger = logging.getLogger(__name__)

# Constants for feature computation
MIN_DATA_POINTS = 60  # Minimum data points for robust calculations
RSI_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BOLLINGER_LENGTH = 20
VaR_CONFIDENCE = 0.95
NIFTY_TICKER = "^NSEI"


class MarketFeatureCalculator:
    """
    Computes market features and risk indicators for financial instruments.

    This calculator integrates with Django ORM to fetch price data and computes
    a comprehensive set of technical indicators and risk metrics suitable for
    ML model training and real-time portfolio risk assessment.

    Attributes:
        ticker_symbol (str): The ticker symbol being analyzed.
        all_tickers (set): Set of all active ticker symbols in watchlist.
    """

    def __init__(self):
        """Initialize the MarketFeatureCalculator."""
        self.ticker_symbol = None
        # Pre-fetch all active tickers for correlation calculation
        self.all_tickers = set(
            Watchlist.objects.filter(is_active=True).values_list(
                'ticker', flat=True
            )
        )

    def compute_all(
        self,
        ticker_symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, float]:
        """
        Compute all market features for a given ticker over a date range.

        This is the main entry point that orchestrates the full feature computation
        pipeline and returns the latest feature snapshot.

        Args:
            ticker_symbol: Stock ticker symbol (e.g., 'RELIANCE', '^NSEI')
            start_date: Start date for data range (datetime or date)
            end_date: End date for data range (datetime or date)

        Returns:
            Dictionary with all computed features for the latest date:
            {
                'daily_return_simple': float,
                'daily_return_log': float,
                'volatility_5d': float,
                'volatility_20d': float,
                'volatility_60d': float,
                'beta_60d': float,
                'correlation_matrix': dict,
                'var_95': float,
                'max_drawdown_60d': float,
                'rsi_14': float,
                'atr_14': float,
                'macd': float,
                'macd_signal': float,
                'macd_histogram': float,
                'bollinger_position': float,
                'volume_breakout': float,
                'high_52w_proximity': float,
            }

        Raises:
            ValueError: If ticker not found or insufficient data.
        """
        self.ticker_symbol = ticker_symbol

        try:
            # Fetch price data from database
            price_df = self._fetch_price_data(ticker_symbol, start_date, end_date)

            if price_df.empty:
                logger.error(f"No price data found for {ticker_symbol}")
                raise ValueError(f"No price data available for {ticker_symbol}")

            if len(price_df) < MIN_DATA_POINTS:
                logger.warning(
                    f"Insufficient data for {ticker_symbol}: {len(price_df)} rows "
                    f"(minimum {MIN_DATA_POINTS} required)"
                )

            # Compute all features
            features = {}

            # Daily returns
            features.update(self._compute_returns(price_df))

            # Volatility (rolling windows)
            features.update(self._compute_volatility(price_df))

            # Beta vs NIFTY 50
            features.update(self._compute_beta(ticker_symbol, price_df, start_date))

            # Correlation matrix
            features.update(self._compute_correlation_matrix(price_df, end_date))

            # Value at Risk (95% confidence)
            features.update(self._compute_var(price_df))

            # Maximum drawdown
            features.update(self._compute_max_drawdown(price_df))

            # Technical indicators
            features.update(self._compute_technical_indicators(price_df))

            # Bollinger Band position
            features.update(self._compute_bollinger_position(price_df))

            # Volume breakout
            features.update(self._compute_volume_breakout(price_df))

            # 52-week high proximity
            features.update(self._compute_52w_proximity(price_df))

            logger.info(f"Successfully computed {len(features)} features for {ticker_symbol}")
            return features

        except Exception as e:
            logger.error(f"Error computing features for {ticker_symbol}: {str(e)}")
            raise

    def _fetch_price_data(
        self,
        ticker_symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV price data from PriceHistory table.

        Args:
            ticker_symbol: Stock ticker symbol
            start_date: Start date for query
            end_date: End date for query

        Returns:
            DataFrame with date index and OHLCV columns
        """
        queryset = PriceHistory.objects.filter(
            ticker=ticker_symbol,
            date__gte=start_date,
            date__lte=end_date,
        ).order_by('date')

        if not queryset.exists():
            logger.warning(f"No data found for {ticker_symbol} in date range")
            return pd.DataFrame()

        # Convert queryset to DataFrame
        data = list(
            queryset.values(
                'date', 'open', 'high', 'low', 'close', 'volume'
            )
        )

        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df = df.sort_index()

        # Convert Decimal to float for numerical operations
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)

        logger.info(f"Fetched {len(df)} price records for {ticker_symbol}")
        return df

    def _compute_returns(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute daily simple and log returns.

        Args:
            df: DataFrame with close prices

        Returns:
            Dictionary with return metrics
        """
        if len(df) < 2:
            return {
                'daily_return_simple': np.nan,
                'daily_return_log': np.nan,
            }

        latest_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]

        if prev_close == 0:
            logger.warning("Previous close price is zero, returning NaN for returns")
            return {
                'daily_return_simple': np.nan,
                'daily_return_log': np.nan,
            }

        # Simple return
        simple_return = (latest_close - prev_close) / prev_close

        # Log return
        log_return = np.log(latest_close / prev_close)

        return {
            'daily_return_simple': float(simple_return),
            'daily_return_log': float(log_return),
        }

    def _compute_volatility(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute rolling volatility over multiple windows.

        Args:
            df: DataFrame with close prices

        Returns:
            Dictionary with volatility metrics for 5d, 20d, 60d
        """
        result = {}

        # Calculate daily returns
        returns = df['close'].pct_change()

        # 5-day volatility
        vol_5d = returns.rolling(window=5).std()
        result['volatility_5d'] = (
            float(vol_5d.iloc[-1]) if not pd.isna(vol_5d.iloc[-1]) else np.nan
        )

        # 20-day volatility
        vol_20d = returns.rolling(window=20).std()
        result['volatility_20d'] = (
            float(vol_20d.iloc[-1]) if not pd.isna(vol_20d.iloc[-1]) else np.nan
        )

        # 60-day volatility
        vol_60d = returns.rolling(window=60).std()
        result['volatility_60d'] = (
            float(vol_60d.iloc[-1]) if not pd.isna(vol_60d.iloc[-1]) else np.nan
        )

        return result

    def _compute_beta(
        self,
        ticker_symbol: str,
        df: pd.DataFrame,
        start_date: datetime,
    ) -> Dict[str, float]:
        """
        Compute rolling 60-day beta vs NIFTY 50.

        Beta = Covariance(ticker_returns, market_returns) / Variance(market_returns)

        Args:
            ticker_symbol: Stock ticker symbol
            df: DataFrame with ticker price data
            start_date: Start date for data range

        Returns:
            Dictionary with beta_60d metric
        """
        # Skip beta calculation for index itself
        if ticker_symbol == NIFTY_TICKER:
            return {'beta_60d': np.nan}

        try:
            # Fetch NIFTY 50 data for the same period
            nifty_df = self._fetch_price_data(NIFTY_TICKER, start_date, df.index[-1])

            if nifty_df.empty or len(nifty_df) < MIN_DATA_POINTS:
                logger.warning(f"Insufficient NIFTY 50 data for beta calculation")
                return {'beta_60d': np.nan}

            # Align both dataframes by date
            aligned_ticker = df['close'].pct_change()
            aligned_nifty = nifty_df['close'].pct_change()

            # Get common dates
            common_index = aligned_ticker.index.intersection(aligned_nifty.index)

            if len(common_index) < MIN_DATA_POINTS:
                logger.warning(f"Insufficient common dates for beta calculation")
                return {'beta_60d': np.nan}

            # Align returns
            ticker_returns = aligned_ticker.loc[common_index]
            nifty_returns = aligned_nifty.loc[common_index]

            # Calculate covariance and variance using rolling 60-day window
            # For latest date, use last 60 days
            window = min(60, len(ticker_returns))
            if window < 60:
                logger.warning(f"Using only {window} days for beta (< 60 days)")

            ticker_ret_window = ticker_returns.iloc[-window:].values
            nifty_ret_window = nifty_returns.iloc[-window:].values

            covariance = np.cov(ticker_ret_window, nifty_ret_window)[0, 1]
            variance = np.var(nifty_ret_window)

            if variance == 0:
                logger.warning(f"Market variance is zero, cannot compute beta")
                return {'beta_60d': np.nan}

            beta = covariance / variance

            return {'beta_60d': float(beta)}

        except Exception as e:
            logger.warning(f"Error computing beta for {ticker_symbol}: {str(e)}")
            return {'beta_60d': np.nan}

    def _compute_correlation_matrix(
        self,
        df: pd.DataFrame,
        end_date: datetime,
    ) -> Dict[str, Dict[str, float]]:
        """
        Compute correlation matrix across all active tickers.

        Args:
            df: DataFrame with ticker price data
            end_date: End date for calculating correlations

        Returns:
            Dictionary with correlation_matrix
        """
        try:
            # Calculate returns for the ticker
            ticker_returns = df['close'].pct_change().dropna()

            if len(ticker_returns) < 20:
                logger.warning("Insufficient data for correlation matrix")
                return {'correlation_matrix': {}}

            correlations = {}

            # Compute correlation with other active tickers (sample up to 20)
            sample_tickers = list(self.all_tickers)[:20]

            for other_ticker in sample_tickers:
                if other_ticker == self.ticker_symbol:
                    continue

                try:
                    other_df = self._fetch_price_data(
                        other_ticker,
                        df.index[0],
                        end_date,
                    )

                    if other_df.empty:
                        continue

                    other_returns = other_df['close'].pct_change().dropna()

                    # Align and compute correlation
                    common_index = ticker_returns.index.intersection(
                        other_returns.index
                    )

                    if len(common_index) < 20:
                        continue

                    corr = ticker_returns.loc[common_index].corr(
                        other_returns.loc[common_index]
                    )
                    correlations[other_ticker] = float(corr)

                except Exception:
                    continue

            return {'correlation_matrix': correlations}

        except Exception as e:
            logger.warning(f"Error computing correlation matrix: {str(e)}")
            return {'correlation_matrix': {}}

    def _compute_var(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute Value at Risk (95% confidence) using historical simulation.

        VaR 95% = 5th percentile of daily returns

        Args:
            df: DataFrame with close prices

        Returns:
            Dictionary with var_95 metric
        """
        if len(df) < 20:
            return {'var_95': np.nan}

        try:
            returns = df['close'].pct_change().dropna()
            var_95 = np.percentile(returns, (1 - VaR_CONFIDENCE) * 100)
            return {'var_95': float(var_95)}

        except Exception as e:
            logger.warning(f"Error computing VaR: {str(e)}")
            return {'var_95': np.nan}

    def _compute_max_drawdown(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute maximum drawdown over 60-day rolling window.

        Drawdown = (Current Price - Peak Price) / Peak Price

        Args:
            df: DataFrame with close prices

        Returns:
            Dictionary with max_drawdown_60d metric
        """
        if len(df) < 60:
            logger.warning("Insufficient data for 60-day max drawdown")
            return {'max_drawdown_60d': np.nan}

        try:
            prices = df['close'].iloc[-60:].values
            cummax = np.maximum.accumulate(prices)
            drawdown = (prices - cummax) / cummax
            max_dd = np.min(drawdown)

            return {'max_drawdown_60d': float(max_dd)}

        except Exception as e:
            logger.warning(f"Error computing max drawdown: {str(e)}")
            return {'max_drawdown_60d': np.nan}

    def _compute_technical_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute technical indicators using pandas_ta.

        Includes RSI, ATR, and MACD.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dictionary with technical indicator values
        """
        result = {}

        if len(df) < RSI_PERIOD:
            logger.warning("Insufficient data for RSI calculation")
            return {
                'rsi_14': np.nan,
                'atr_14': np.nan,
                'macd': np.nan,
                'macd_signal': np.nan,
                'macd_histogram': np.nan,
            }

        try:
            # RSI (14-period)
            rsi = ta.rsi(df['close'], length=RSI_PERIOD)
            result['rsi_14'] = (
                float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else np.nan
            )

        except Exception as e:
            logger.warning(f"Error computing RSI: {str(e)}")
            result['rsi_14'] = np.nan

        try:
            # ATR (14-period)
            atr = ta.atr(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                length=ATR_PERIOD,
            )
            result['atr_14'] = (
                float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else np.nan
            )

        except Exception as e:
            logger.warning(f"Error computing ATR: {str(e)}")
            result['atr_14'] = np.nan

        try:
            # MACD (12/26/9)
            macd_result = ta.macd(
                df['close'],
                fast=MACD_FAST,
                slow=MACD_SLOW,
                signal=MACD_SIGNAL,
            )

            macd_col = f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
            signal_col = f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
            hist_col = f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'

            result['macd'] = (
                float(macd_result[macd_col].iloc[-1])
                if macd_col in macd_result.columns
                else np.nan
            )
            result['macd_signal'] = (
                float(macd_result[signal_col].iloc[-1])
                if signal_col in macd_result.columns
                else np.nan
            )
            result['macd_histogram'] = (
                float(macd_result[hist_col].iloc[-1])
                if hist_col in macd_result.columns
                else np.nan
            )

        except Exception as e:
            logger.warning(f"Error computing MACD: {str(e)}")
            result['macd'] = np.nan
            result['macd_signal'] = np.nan
            result['macd_histogram'] = np.nan

        return result

    def _compute_bollinger_position(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute Bollinger Band position (0.0 to 1.0).

        Position = (Current Price - Lower Band) / (Upper Band - Lower Band)

        Args:
            df: DataFrame with close prices

        Returns:
            Dictionary with bollinger_position metric
        """
        if len(df) < BOLLINGER_LENGTH:
            return {'bollinger_position': np.nan}

        try:
            bbands = ta.bbands(df['close'], length=BOLLINGER_LENGTH)

            if bbands is None or bbands.empty:
                return {'bollinger_position': np.nan}

            # Column names: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
            col_suffix = f'_{BOLLINGER_LENGTH}_2.0'
            lower_col = f'BBL{col_suffix}'
            upper_col = f'BBU{col_suffix}'

            if lower_col not in bbands.columns or upper_col not in bbands.columns:
                logger.warning("Unexpected Bollinger Band columns")
                return {'bollinger_position': np.nan}

            latest_close = df['close'].iloc[-1]
            lower_band = bbands[lower_col].iloc[-1]
            upper_band = bbands[upper_col].iloc[-1]

            band_range = upper_band - lower_band

            if band_range == 0:
                position = 0.5
            else:
                position = (latest_close - lower_band) / band_range

            # Clamp to [0, 1]
            position = max(0.0, min(1.0, position))

            return {'bollinger_position': float(position)}

        except Exception as e:
            logger.warning(f"Error computing Bollinger position: {str(e)}")
            return {'bollinger_position': np.nan}

    def _compute_volume_breakout(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute volume breakout signal.

        Volume Breakout = Current Volume / 20-day Average Volume

        Args:
            df: DataFrame with volume data

        Returns:
            Dictionary with volume_breakout metric
        """
        if len(df) < 20:
            return {'volume_breakout': np.nan}

        try:
            current_volume = df['volume'].iloc[-1]
            avg_volume = df['volume'].iloc[-20:].mean()

            if avg_volume == 0:
                logger.warning("Average volume is zero")
                return {'volume_breakout': np.nan}

            breakout = current_volume / avg_volume
            return {'volume_breakout': float(breakout)}

        except Exception as e:
            logger.warning(f"Error computing volume breakout: {str(e)}")
            return {'volume_breakout': np.nan}

    def _compute_52w_proximity(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute proximity to 52-week high.

        52-Week Proximity = Current Price / 52-Week High

        Args:
            df: DataFrame with close prices

        Returns:
            Dictionary with high_52w_proximity metric
        """
        # 252 trading days ≈ 1 year
        lookback = min(252, len(df))

        if lookback < 20:
            return {'high_52w_proximity': np.nan}

        try:
            latest_close = df['close'].iloc[-1]
            high_52w = df['close'].iloc[-lookback:].max()

            if high_52w == 0:
                return {'high_52w_proximity': np.nan}

            proximity = latest_close / high_52w

            return {'high_52w_proximity': float(proximity)}

        except Exception as e:
            logger.warning(f"Error computing 52-week proximity: {str(e)}")
            return {'high_52w_proximity': np.nan}

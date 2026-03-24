import logging
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from typing import List, Optional

logger = logging.getLogger(__name__)


class PreprocessingPipeline:
    """
    A comprehensive preprocessing pipeline for financial time series data.

    This class handles common preprocessing tasks for OHLCV (Open, High, Low, Close, Volume)
    financial data including missing value imputation, outlier detection, timestamp alignment,
    and feature normalization.

    Attributes:
        scaler (StandardScaler): Fitted StandardScaler for feature normalization.
    """

    def __init__(self):
        """Initialize the preprocessing pipeline."""
        self.scaler = None

    def handle_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Handle missing values in the DataFrame.

        For OHLC columns (Open, High, Low, Close): Forward fill missing values.
        For Volume column: Fill with median value.
        For other columns: Forward fill, then backward fill as fallback.

        Args:
            df: Input DataFrame with date index and OHLCV columns.

        Returns:
            DataFrame with missing values handled.

        Raises:
            ValueError: If DataFrame is empty or has no valid columns.
        """
        if df.empty:
            raise ValueError("Input DataFrame is empty")

        df = df.copy()

        # Define OHLC columns
        ohlc_cols = ['Open', 'High', 'Low', 'Close']
        volume_col = 'Volume'

        # Check for data quality issues
        total_missing = df.isnull().sum().sum()
        if total_missing > 0:
            logger.warning(f"Found {total_missing} missing values in DataFrame")

        # Handle OHLC columns with forward fill
        for col in ohlc_cols:
            if col in df.columns:
                missing_count = df[col].isnull().sum()
                if missing_count > 0:
                    df[col] = df[col].fillna(method='ffill')
                    logger.warning(f"Forward filled {missing_count} missing values in {col}")

        # Handle Volume column with median fill
        if volume_col in df.columns:
            missing_count = df[volume_col].isnull().sum()
            if missing_count > 0:
                median_volume = df[volume_col].median()
                df[volume_col] = df[volume_col].fillna(median_volume)
                logger.warning(f"Filled {missing_count} missing values in {volume_col} with median: {median_volume}")

        # Handle any remaining columns with forward fill, then backward fill
        remaining_cols = df.columns.difference(ohlc_cols + [volume_col])
        for col in remaining_cols:
            missing_count = df[col].isnull().sum()
            if missing_count > 0:
                df[col] = df[col].fillna(method='ffill').fillna(method='bfill')
                logger.warning(f"Handled {missing_count} missing values in {col} with forward/backward fill")

        return df

    def detect_outliers(self, df: pd.DataFrame, column: str, z_threshold: float = 3.0) -> pd.Series:
        """
        Detect outliers in a specified column using z-score method.

        Args:
            df: Input DataFrame.
            column: Column name to check for outliers.
            z_threshold: Z-score threshold for outlier detection (default: 3.0).

        Returns:
            Boolean Series where True indicates an outlier.

        Raises:
            ValueError: If column doesn't exist or has insufficient data.
        """
        if column not in df.columns:
            raise ValueError(f"Column '{column}' not found in DataFrame")

        if len(df) < 2:
            logger.warning("DataFrame has fewer than 2 rows, cannot compute z-scores")
            return pd.Series([False] * len(df), index=df.index)

        # Calculate z-scores
        mean_val = df[column].mean()
        std_val = df[column].std()

        if std_val == 0:
            logger.warning(f"Column '{column}' has zero standard deviation, no outliers detected")
            return pd.Series([False] * len(df), index=df.index)

        z_scores = np.abs((df[column] - mean_val) / std_val)
        outliers = z_scores > z_threshold

        outlier_count = outliers.sum()
        if outlier_count > 0:
            logger.warning(f"Detected {outlier_count} outliers in column '{column}' using z-threshold {z_threshold}")

        return outliers

    def align_timestamps(self, df_list: List[pd.DataFrame]) -> List[pd.DataFrame]:
        """
        Align timestamps across multiple DataFrames by reindexing to common date range.

        Args:
            df_list: List of DataFrames with date indices.

        Returns:
            List of DataFrames with aligned date indices.

        Raises:
            ValueError: If df_list is empty or DataFrames don't have date indices.
        """
        if not df_list:
            raise ValueError("Input list of DataFrames is empty")

        # Validate that all DataFrames have date indices
        for i, df in enumerate(df_list):
            if not isinstance(df.index, pd.DatetimeIndex):
                try:
                    df_list[i] = df.set_index(pd.to_datetime(df.index))
                    logger.warning(f"Converted index to DatetimeIndex for DataFrame {i}")
                except Exception as e:
                    raise ValueError(f"DataFrame {i} does not have a valid date index: {e}")

        # Find the union of all dates
        all_dates = set()
        for df in df_list:
            all_dates.update(df.index)

        common_dates = sorted(all_dates)
        logger.info(f"Aligning {len(df_list)} DataFrames to {len(common_dates)} common dates")

        # Reindex each DataFrame to common dates
        aligned_dfs = []
        for i, df in enumerate(df_list):
            aligned_df = df.reindex(common_dates)
            aligned_dfs.append(aligned_df)
            logger.info(f"DataFrame {i}: {len(df)} -> {len(aligned_df)} rows after alignment")

        return aligned_dfs

    def normalize_features(self, df: pd.DataFrame, method: str = 'standard') -> pd.DataFrame:
        """
        Normalize numerical features in the DataFrame.

        Currently supports 'standard' normalization using StandardScaler.

        Args:
            df: Input DataFrame with numerical columns to normalize.
            method: Normalization method ('standard' only for now).

        Returns:
            DataFrame with normalized features.

        Raises:
            ValueError: If method is not supported or DataFrame has no numerical columns.
        """
        if method != 'standard':
            raise ValueError(f"Unsupported normalization method: {method}")

        if df.empty:
            raise ValueError("Input DataFrame is empty")

        df = df.copy()

        # Select numerical columns
        numerical_cols = df.select_dtypes(include=[np.number]).columns
        if len(numerical_cols) == 0:
            logger.warning("No numerical columns found for normalization")
            return df

        logger.info(f"Normalizing {len(numerical_cols)} numerical columns: {list(numerical_cols)}")

        # Initialize or fit scaler
        if self.scaler is None:
            self.scaler = StandardScaler()

        # Fit and transform
        try:
            df[numerical_cols] = self.scaler.fit_transform(df[numerical_cols])
            logger.info("Features normalized successfully")
        except Exception as e:
            logger.error(f"Error during normalization: {e}")
            raise

        return df
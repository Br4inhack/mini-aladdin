"""
Common helper functions for the CRPMS project.
Used across agents, engines, and the API layer.
All database queries are wrapped in try/except to prevent crashes.
"""

import logging
from typing import List
from django.utils import timezone
import pytz
from apps.portfolio.models import Watchlist, Position

logger = logging.getLogger('utils.helpers')


def get_active_tickers() -> List[str]:
    """
    Retrieves a list of all active ticker symbols from the Watchlist.

    Returns:
        List[str]: A list of ticker strings (e.g., ['RELIANCE', 'TCS']).
        Returns an empty list if the database query fails.
    """
    try:
        # Use values_list with flat=True for efficient database querying
        return list(Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True))
    except Exception as e:
        logger.error(f"DB query failed in get_active_tickers: {str(e)}")
        return []


def get_portfolio_tickers() -> List[str]:
    """
    Retrieves a list of unique ticker symbols that currently have
    an active position in any portfolio.

    Returns:
        List[str]: A list of ticker strings.
        Returns an empty list if the database query fails.
    """
    try:
        # Using distinct to avoid duplicates if multiple portfolios hold the same asset
        return list(
            Position.objects.select_related('watchlist')
            .filter(quantity__gt=0)
            .values_list('watchlist__ticker', flat=True)
            .distinct()
        )
    except Exception as e:
        logger.error(f"DB query failed in get_portfolio_tickers: {str(e)}")
        return []


def get_ist_now():
    """
    Returns the current datetime in the Asia/Kolkata timezone.

    Returns:
        datetime.datetime: Current timezone-aware datetime in IST.
    """
    ist_tz = pytz.timezone("Asia/Kolkata")
    return timezone.now().astimezone(ist_tz)


def is_market_hours() -> bool:
    """
    Checks if the current Indian Standard Time (IST) falls within
    standard equity market hours: Monday-Friday, 09:15 to 15:30.

    Returns:
        bool: True if market is open, False otherwise.
    """
    now = get_ist_now()
    
    # Check if weekend (Monday = 0, Sunday = 6)
    if now.weekday() >= 5:
        return False
        
    current_time = now.time()
    
    # 09:15 as float representation: 9 + (15/60) = 9.25
    # 15:30 as float representation: 15 + (30/60) = 15.5
    current_float = current_time.hour + (current_time.minute / 60.0)
    
    return 9.25 <= current_float <= 15.5


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divides two numbers, preventing ZeroDivisionError.

    Args:
        numerator (float): The dividend.
        denominator (float): The divisor.
        default (float, optional): The value to return if denominator is zero. Defaults to 0.0.

    Returns:
        float: The quotient or the default value.
    """
    try:
        num = float(numerator)
        den = float(denominator)
        if den == 0.0:
            return float(default)
        return num / den
    except (ValueError, TypeError):
        return float(default)


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Restricts a value within a specified min and max range.

    Args:
        value (float): The value to be clamped.
        min_val (float): The lower bound.
        max_val (float): The upper bound.

    Returns:
        float: The clamped value.
    """
    try:
        val = float(value)
        minimum = float(min_val)
        maximum = float(max_val)
        return max(minimum, min(val, maximum))
    except (ValueError, TypeError):
        # Fallback to min_val if inputs are entirely invalid
        return float(min_val)


def normalise_score(value: float, min_val: float, max_val: float) -> float:
    """
    Normalises a score to a 0-100 percentage range based on its min/max bounds.
    If value falls outside the bounds, it is clamped.
    If min_val == max_val, returns 50.0 to prevent division by zero.

    Args:
        value (float): The raw score to normalise.
        min_val (float): Theoretical minimum possible score.
        max_val (float): Theoretical maximum possible score.

    Returns:
        float: A normalised score strictly between 0.0 and 100.0.
    """
    try:
        val = float(value)
        minimum = float(min_val)
        maximum = float(max_val)
        
        if minimum >= maximum:
            return 50.0
            
        clamped_val = clamp(val, minimum, maximum)
        normalised = ((clamped_val - minimum) / (maximum - minimum)) * 100.0
        return float(normalised)
    except (ValueError, TypeError):
        return 0.0

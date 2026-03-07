"""
General helper utilities for CRPMS.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone

logger = logging.getLogger('apps')


def to_decimal(value, places: int = 6) -> Decimal:
    """
    Safely convert a float/int/str to a Decimal with controlled precision.

    Args:
        value: Numeric value to convert.
        places: Number of decimal places to round to.

    Returns:
        Decimal value.
    """
    try:
        quantize_str = Decimal(10) ** -places
        return Decimal(str(value)).quantize(quantize_str, rounding=ROUND_HALF_UP)
    except Exception as exc:
        logger.error("to_decimal conversion failed for value=%s: %s", value, exc)
        return Decimal('0')


def pct(value: float, total: float) -> float:
    """
    Calculate percentage safely (avoids ZeroDivisionError).

    Args:
        value: Numerator.
        total: Denominator.

    Returns:
        Float percentage (0.0 to 1.0), or 0.0 if total is zero.
    """
    if not total:
        return 0.0
    return value / total


def now_utc():
    """Return current UTC-aware datetime."""
    return timezone.now()


def is_market_hours() -> bool:
    """
    Rough check whether US markets are currently open.
    Uses UTC time — market hours are 14:30–21:00 UTC (9:30am–4:00pm ET).

    Returns:
        True if likely within US market hours on a weekday.
    """
    now = timezone.now()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=14, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=21, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def chunk_list(lst: list, size: int) -> list:
    """
    Split a list into chunks of a given size.

    Args:
        lst: Input list.
        size: Maximum chunk size.

    Returns:
        List of sub-lists.
    """
    return [lst[i:i + size] for i in range(0, len(lst), size)]

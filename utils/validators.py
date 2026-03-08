"""
Input validation functions for the CRPMS API endpoints and agent payloads.
All database queries are wrapped in try/except blocks.
"""

import logging
from apps.portfolio.models import Watchlist, DecisionLog

logger = logging.getLogger('utils.validators')


def is_valid_ticker(ticker: str) -> bool:
    """
    Validates whether a given ticker exists in the Watchlist and is marked active.

    Args:
        ticker (str): The ticker symbol to validate (e.g., 'TCS').

    Returns:
        bool: True if the ticker is valid and active, False otherwise.
        Returns False if a database error occurs.
    """
    if not isinstance(ticker, str) or not ticker.strip():
        return False
        
    try:
        # filter().exists() is the most performant way to check existence
        return Watchlist.objects.filter(ticker=ticker.strip(), is_active=True).exists()
    except Exception as e:
        logger.error(f"DB query failed in is_valid_ticker for {ticker}: {str(e)}")
        return False


def is_valid_score(score: float) -> bool:
    """
    Validates whether an agent or feature score falls within the standard
    0 to 100 range.

    Args:
        score (float): The numeric score to validate.

    Returns:
        bool: True if 0 <= score <= 100, False otherwise.
    """
    try:
        s = float(score)
        return 0.0 <= s <= 100.0
    except (ValueError, TypeError):
        return False


def is_valid_action(action: str) -> bool:
    """
    Validates whether a suggested action matches one of the accepted
    DecisionLog Action TextChoices values.

    Args:
        action (str): The string representing the action 
                      (e.g., 'HOLD', 'REDUCE', 'EXIT', 'INCREASE', 'REALLOCATE').

    Returns:
        bool: True if the action is valid, False otherwise.
    """
    if not isinstance(action, str):
        return False
        
    try:
        action_val = action.strip().upper()
        # DecisionLog.Action.values returns a list of the enum values
        return action_val in DecisionLog.Action.values
    except Exception as e:
        logger.error(f"Validation failed in is_valid_action for {action}: {str(e)}")
        return False

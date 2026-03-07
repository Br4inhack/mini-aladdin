"""
Cache utilities for CRPMS — thin wrappers around Django's cache framework.

Usage:
    from utils.cache import get_portfolio_state, set_portfolio_state
"""

import logging
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger('apps')


def get_portfolio_state(portfolio_id: int) -> dict | None:
    """
    Retrieve the latest portfolio state snapshot from Redis cache.

    Args:
        portfolio_id: The primary key of the Portfolio model instance.

    Returns:
        A dict of portfolio state data, or None if not cached.
    """
    ttl = settings.CRPMS.get('CACHE_TTL_PORTFOLIO_STATE', 60)
    key = f'portfolio_state:{portfolio_id}'
    try:
        return cache.get(key)
    except Exception as exc:
        logger.error("Cache get failed for key=%s: %s", key, exc)
        return None


def set_portfolio_state(portfolio_id: int, state: dict) -> bool:
    """
    Write portfolio state dict to Redis cache.

    Args:
        portfolio_id: The primary key of the Portfolio model instance.
        state: Dict containing portfolio state data.

    Returns:
        True if the cache set succeeded, False otherwise.
    """
    ttl = settings.CRPMS.get('CACHE_TTL_PORTFOLIO_STATE', 60)
    key = f'portfolio_state:{portfolio_id}'
    try:
        cache.set(key, state, timeout=ttl)
        return True
    except Exception as exc:
        logger.error("Cache set failed for key=%s: %s", key, exc)
        return False


def get_agent_output(agent_name: str, ticker: str) -> dict | None:
    """
    Retrieve the latest agent output from Redis cache.

    Args:
        agent_name: One of the AGENT_NAMES choices.
        ticker: Asset ticker symbol.

    Returns:
        A dict of agent output data, or None if not cached.
    """
    key = f'agent_output:{agent_name}:{ticker}'
    try:
        return cache.get(key)
    except Exception as exc:
        logger.error("Cache get failed for key=%s: %s", key, exc)
        return None


def set_agent_output(agent_name: str, ticker: str, output: dict) -> bool:
    """
    Write agent output to Redis cache.

    Args:
        agent_name: One of the AGENT_NAMES choices.
        ticker: Asset ticker symbol.
        output: Dict of agent output data.

    Returns:
        True if cache set succeeded.
    """
    ttl = settings.CRPMS.get('CACHE_TTL_AGENT_OUTPUT', 300)
    key = f'agent_output:{agent_name}:{ticker}'
    try:
        cache.set(key, output, timeout=ttl)
        return True
    except Exception as exc:
        logger.error("Cache set failed for key=%s: %s", key, exc)
        return False


def invalidate_portfolio_cache(portfolio_id: int) -> None:
    """Remove cached portfolio state for a given portfolio."""
    key = f'portfolio_state:{portfolio_id}'
    try:
        cache.delete(key)
    except Exception as exc:
        logger.error("Cache delete failed for key=%s: %s", key, exc)

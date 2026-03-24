"""
Centralised Redis cache operations for the CRPMS project.
All functions fail gracefully to ensure the system keeps running
even if Redis is unavailable.
"""

import logging
from typing import Optional, Dict, Any
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger('utils.cache')

# Fallback TTL if CRPMS setting isn't available
DEFAULT_AGENT_TTL = getattr(settings, 'CRPMS', {}).get('AGENT_OUTPUT_TTL_SECONDS', 3600)


def get_agent_output(agent_name: str, ticker: str) -> Optional[Dict[str, Any]]:
    """
    Reads the latest output for a specific agent and ticker from cache.

    Args:
        agent_name (str): The name of the agent (e.g., 'market_risk', 'sentiment').
        ticker (str): The instrument ticker symbol.

    Returns:
        Optional[Dict[str, Any]]: The cached agent output dict, or None if missing or on error.
    """
    key = f"agent:{agent_name}:{ticker}"
    try:
        return cache.get(key)
    except Exception as e:
        logger.error(f"Redis get failed for key {key}: {str(e)}")
        return None


def set_agent_output(agent_name: str, ticker: str, data: Dict[str, Any]) -> bool:
    """
    Writes agent output to cache with the configured TTL.

    Args:
        agent_name (str): The name of the agent.
        ticker (str): The instrument ticker symbol.
        data (Dict[str, Any]): The agent output data payload.

    Returns:
        bool: True if cache set was successful, False otherwise.
    """
    key = f"agent:{agent_name}:{ticker}"
    ttl = getattr(settings, 'CRPMS', {}).get('AGENT_OUTPUT_TTL_SECONDS', DEFAULT_AGENT_TTL)
    try:
        cache.set(key, data, timeout=ttl)
        return True
    except Exception as e:
        logger.error(f"Redis set failed for key {key}: {str(e)}")
        return False


def get_portfolio_state() -> Optional[Dict[str, Any]]:
    """
    Reads the full aggregated portfolio state from cache.

    Returns:
        Optional[Dict[str, Any]]: The portfolio state dict, or None if missing or on error.
    """
    key = "portfolio:current_state"
    try:
        return cache.get(key)
    except Exception as e:
        logger.error(f"Redis get failed for key {key}: {str(e)}")
        return None


def set_portfolio_state(state: Dict[str, Any]) -> bool:
    """
    Writes the aggregated portfolio state to cache.
    Hardcoded TTL of 900 seconds (15 minutes).

    Args:
        state (Dict[str, Any]): The portfolio state serialised dictionary.

    Returns:
        bool: True if cache set was successful, False otherwise.
    """
    key = "portfolio:current_state"
    try:
        cache.set(key, state, timeout=900)
        return True
    except Exception as e:
        logger.error(f"Redis set failed for key {key}: {str(e)}")
        return False


def get_all_agent_outputs_for_ticker(ticker: str) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Fetches the outputs of all four core agents for a specific ticker.

    Args:
        ticker (str): The instrument ticker symbol.

    Returns:
        Dict[str, Optional[Dict[str, Any]]]: A dictionary mapping agent names to their
        respective outputs. Values may be None if not cached.
    """
    agents = ['market_risk', 'sentiment', 'fundamental', 'opportunity']
    keys = {agent: f"agent:{agent}:{ticker}" for agent in agents}
    
    results = {agent: None for agent in agents}
    try:
        cached_values = cache.get_many(keys.values())
        for agent, key in keys.items():
            results[agent] = cached_values.get(key)
    except Exception as e:
        logger.error(f"Redis get_many failed for ticker {ticker}: {str(e)}")
        # On error, we still return the dict with None values, avoiding system crash.
        
    return results


def invalidate_ticker_cache(ticker: str) -> None:
    """
    Deletes all cached agent outputs for a given ticker.

    Args:
        ticker (str): The instrument ticker symbol to invalidate.
    """
    agents = ['market_risk', 'sentiment', 'fundamental', 'opportunity']
    keys = [f"agent:{agent}:{ticker}" for agent in agents]
    try:
        cache.delete_many(keys)
    except Exception as e:
        logger.error(f"Redis delete_many failed for ticker {ticker}: {str(e)}")


def health_check() -> bool:
    """
    Tests cache connectivity by writing, reading, and deleting a test key.

    Returns:
        bool: True if Redis is fully operational, False otherwise.
    """
    test_key = "health_check:test_key"
    try:
        cache.set(test_key, "ok", timeout=10)
        val = cache.get(test_key)
        cache.delete(test_key)
        return val == "ok"
    except Exception as e:
        logger.error(f"Redis health_check failed: {str(e)}")
        return False

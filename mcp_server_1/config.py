"""
MCP Server 1 configuration — connection pooling, rate limits, caching.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8100
    DEBUG: bool = True

    # Django integration
    DJANGO_SETTINGS_MODULE: str = "config.settings"

    # Connection pooling — httpx async client
    HTTP_POOL_MAX_CONNECTIONS: int = 20
    HTTP_POOL_MAX_KEEPALIVE: int = 10
    HTTP_TIMEOUT_SECONDS: float = 30.0

    # Request cache (in-memory TTL cache)
    CACHE_TTL_PRICE: int = 300        # 5 min for price data
    CACHE_TTL_FUNDAMENTALS: int = 3600  # 1 hour for fundamentals
    CACHE_TTL_MACRO: int = 3600        # 1 hour for macro data

    # Rate limits (requests per minute)
    RATE_LIMIT_YFINANCE: int = 30
    RATE_LIMIT_FRED: int = 20
    RATE_LIMIT_RBI: int = 10
    RATE_LIMIT_NSE: int = 15

    class Config:
        env_prefix = "MCP1_"
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

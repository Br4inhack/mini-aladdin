"""
db_writer.py — Person 4 (Sentiment Agent)
==========================================
Writes pipeline results to the four database models that Person 4 owns.

IMPORTANT — Real field names from Person 1's models (apps/portfolio/models.py):
  NewsArticle  → ticker_tag (FK), headline, source, url, sentiment_score,
                  published_at, processed_at, content_hash
  AgentOutput  → ticker (FK), agent_name, score, band, flags, raw_data, timestamp
  DecisionLog  → ticker (FK), action, confidence_score, reasoning_text,
                  input_signals, timestamp
  DataIngestionLog → source_name, ticker (CharField, NOT FK), status,
                      error_message, records_fetched, timestamp (auto)

Architecture Rules followed here:
  Rule 1  — ticker FK is always a Watchlist instance, NEVER a string
  Rule 3  — every run writes a DataIngestionLog (even on failure)
  Rule 4  — deduplication via content_hash (SHA-256 of headline+published_at)
  Rule 5  — event_risk_flag forces band = CRITICAL (already done in pipeline,
             double-checked here)
"""

import hashlib
import logging
from datetime import datetime, timezone as dt_timezone
from dateutil import parser as dateutil_parser  # pip install python-dateutil

from django.utils import timezone

from apps.portfolio.models import (
    Watchlist,
    NewsArticle,
    AgentOutput,
    DecisionLog,
    DataIngestionLog,
)

logger = logging.getLogger(__name__)


# ─── Internal Helpers ────────────────────────────────────────────────────────

def _get_watchlist(company_name: str):
    """
    Looks up the Watchlist instance for a given company name.
    Tries company_name match first, then ticker match (case-insensitive).

    Returns Watchlist instance or None.
    Architecture Rule 1: always return the ORM instance, never a string.
    """
    # Try company_name field (partial, case-insensitive)
    qs = Watchlist.objects.filter(
        company_name__icontains=company_name
    )
    if qs.exists():
        return qs.first()
    # Fallback: try ticker field (useful for ticker-style inputs)
    qs = Watchlist.objects.filter(
        ticker__iexact=company_name
    )
    if qs.exists():
        return qs.first()
    return None


def _make_content_hash(headline: str, published_str: str) -> str:
    """
    Produces a SHA-256 content_hash for deduplication.
    (Architecture Rule 4 — never process the same article twice.)

    Uses headline + published_at string as the composite unique key.
    """
    raw = (headline.strip().lower() + published_str.strip().lower()).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_published(published_str: str):
    """
    Parses the RSS published string into a timezone-aware datetime.
    Falls back to now() if parsing fails.
    """
    if not published_str:
        return timezone.now()
    try:
        dt = dateutil_parser.parse(published_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except Exception:
        return timezone.now()


# ─── write_news_article ──────────────────────────────────────────────────────

def write_news_article(company_name: str, entry, sentiment_result: dict):
    """
    Writes a single NewsArticle record for one RSS entry.

    Parameters
    ----------
    company_name     : str  — used to find the Watchlist FK
    entry            : feedparser entry object from rss_reader.fetch_rss()
    sentiment_result : dict — single article FinBERT result
                              {'label': 'positive', 'score': 0.87}

    Returns
    -------
    NewsArticle instance or None if write fails / duplicate detected.
    """
    try:
        watchlist = _get_watchlist(company_name)
        if watchlist is None:
            logger.warning(
                f"[write_news_article] Watchlist not found for '{company_name}'"
                f" — skipping DB write."
            )
            return None

        headline       = entry.get("title", "").strip()
        published_str  = entry.get("published", "")
        source         = entry.get("source", {}).get("title", "") if isinstance(
                             entry.get("source"), dict) else str(entry.get("source", ""))
        url            = entry.get("link", "")
        published_at   = _parse_published(published_str)

        # Architecture Rule 4: dedup by content_hash
        content_hash = _make_content_hash(headline, published_str)
        if NewsArticle.objects.filter(content_hash=content_hash).exists():
            logger.debug(
                f"[write_news_article] Duplicate article skipped: {headline[:60]}"
            )
            return None

        # Map FinBERT label to -1 / 0 / +1 numeric score (weighted by confidence)
        label = sentiment_result.get("label", "neutral")
        score = sentiment_result.get("score", 0.0)
        label_map = {"positive": 1, "neutral": 0, "negative": -1}
        numeric_score = label_map.get(label, 0) * score   # -1..+1

        article = NewsArticle.objects.create(
            ticker_tag      = watchlist,        # FK instance (Architecture Rule 1)
            headline        = headline,
            source          = source[:100],     # max_length=100
            url             = url[:500],        # max_length=500
            sentiment_score = numeric_score,
            published_at    = published_at,
            processed_at    = timezone.now(),
            content_hash    = content_hash,
        )
        logger.info(f"[write_news_article] Saved: {headline[:60]}")
        return article

    except Exception as exc:
        logger.error(f"[write_news_article] Failed for '{company_name}': {exc}")
        return None


# ─── write_agent_output ──────────────────────────────────────────────────────

def write_agent_output(company_name: str, pipeline_result: dict):
    """
    Writes (or updates) an AgentOutput record for the sentiment agent.

    CRITICAL: Person 1's Portfolio Agent reads this table.
    agent_name must be exactly 'sentiment' (TextChoices value).

    Parameters
    ----------
    company_name    : str  — used to find Watchlist FK
    pipeline_result : dict — output of sentiment_pipeline.run_pipeline()

    Returns
    -------
    AgentOutput instance or None if write fails.
    """
    try:
        watchlist = _get_watchlist(company_name)
        if watchlist is None:
            logger.warning(
                f"[write_agent_output] Watchlist not found for '{company_name}'"
                f" — skipping DB write."
            )
            return None

        sentiment_score = pipeline_result.get("sentiment_score", 0.0)
        event_risk_flag = pipeline_result.get("event_risk_flag", False)
        band            = pipeline_result.get("band", "MEDIUM")
        score_0_to_100  = pipeline_result.get("score", 50.0)
        confidence      = pipeline_result.get("confidence", 0.0)

        # Architecture Rule 5: event_risk_flag always forces CRITICAL
        if event_risk_flag:
            band = "CRITICAL"

        # flags dict — stores event_risk_flag and other binary signals
        flags = {
            "event_risk_flag"   : event_risk_flag,
            "articles_analysed" : pipeline_result.get("articles_analysed", 0),
        }

        # raw_data — full audit trail (Architecture Rule: store everything here)
        raw_data = {
            "company_name"      : company_name,
            "overall_sentiment" : pipeline_result.get("overall_sentiment", "neutral"),
            "sentiment_score"   : sentiment_score,
            "confidence"        : confidence,
            "articles_analysed" : pipeline_result.get("articles_analysed", 0),
            "event_risk_flag"   : event_risk_flag,
            "band"              : band,
            "top_headlines"     : pipeline_result.get("top_headlines", []),
            "raw_sentiments"    : pipeline_result.get("raw_sentiments", []),
        }

        agent_output = AgentOutput.objects.create(
            ticker     = watchlist,                         # FK (Architecture Rule 1)
            agent_name = AgentOutput.AgentName.SENTIMENT,  # must be exactly 'sentiment'
            score      = score_0_to_100,                   # 0-100
            band       = band,                             # LOW / MEDIUM / HIGH / CRITICAL
            flags      = flags,
            raw_data   = raw_data,
        )
        logger.info(
            f"[write_agent_output] Saved AgentOutput for '{company_name}'"
            f" score={score_0_to_100:.2f} band={band}"
        )
        return agent_output

    except Exception as exc:
        logger.error(f"[write_agent_output] Failed for '{company_name}': {exc}")
        return None


# ─── write_decision_log ──────────────────────────────────────────────────────

def write_decision_log(
    company_name: str,
    action: str,
    confidence: float,
    pipeline_result: dict,
    market_risk_data: dict,
):
    """
    Writes a DecisionLog record after apply_rules() has determined the action.

    CRITICAL: Person 1's Portfolio Agent reads this table.
    action must be exactly one of: HOLD, REDUCE, EXIT, INCREASE, REALLOCATE.

    Parameters
    ----------
    company_name     : str   — used to find Watchlist FK
    action           : str   — one of HOLD/REDUCE/EXIT/INCREASE/REALLOCATE
    confidence       : float — from decision_rules.apply_rules()
    pipeline_result  : dict  — from sentiment_pipeline.run_pipeline()
    market_risk_data : dict  — latest AgentOutput row for agent_name='market_risk'
                               (may be empty dict if Person 3 hasn't run yet)

    Returns
    -------
    DecisionLog instance or None if write fails.
    """
    try:
        watchlist = _get_watchlist(company_name)
        if watchlist is None:
            logger.warning(
                f"[write_decision_log] Watchlist not found for '{company_name}'"
                f" — skipping DB write."
            )
            return None

        sentiment_score = pipeline_result.get("sentiment_score", 0.0)
        event_risk_flag = pipeline_result.get("event_risk_flag", False)

        # input_signals — exact keys required by Person 1's Portfolio Agent
        input_signals = {
            "sentiment_score"   : sentiment_score,
            "sentiment_trend"   : 0.0,          # placeholder (no historical trend yet)
            "event_risk_flag"   : event_risk_flag,
            "mention_spike_flag": False,         # placeholder (no spike detection yet)
            "market_risk_band"  : market_risk_data.get("band", "UNKNOWN"),
            "market_risk_score" : market_risk_data.get("score", 0.0),
        }

        # Human-readable reasoning text for the decision
        overall    = pipeline_result.get("overall_sentiment", "neutral")
        band       = pipeline_result.get("band", "MEDIUM")
        mrb        = market_risk_data.get("band", "UNKNOWN")
        reasoning_text = (
            f"Sentiment: {overall} (score={sentiment_score:.3f}, band={band}). "
            f"Market risk band (Person 3): {mrb}. "
            f"Event risk flag: {event_risk_flag}. "
            f"Decision action: {action} (confidence={confidence:.2f})."
        )

        decision_log = DecisionLog.objects.create(
            ticker           = watchlist,    # FK (Architecture Rule 1)
            action           = action,       # HOLD / REDUCE / EXIT / INCREASE / REALLOCATE
            confidence_score = confidence,   # 0.0 to 1.0
            reasoning_text   = reasoning_text,
            input_signals    = input_signals,
        )
        logger.info(
            f"[write_decision_log] Saved DecisionLog for '{company_name}'"
            f" action={action} confidence={confidence:.2f}"
        )
        return decision_log

    except Exception as exc:
        logger.error(f"[write_decision_log] Failed for '{company_name}': {exc}")
        return None


# ─── write_ingestion_log ─────────────────────────────────────────────────────

def write_ingestion_log(
    company_name: str,
    status: str,
    records_fetched: int,
    error_message: str = "",
):
    """
    Writes a DataIngestionLog audit record.

    Architecture Rule 3: every pipeline run writes this — even on failure.

    Parameters
    ----------
    company_name    : str — descriptive name for the ticker field (CharField, NOT FK)
    status          : str — 'SUCCESS', 'PARTIAL', or 'FAILED'
    records_fetched : int — number of articles processed
    error_message   : str — populated only on failure

    Returns
    -------
    DataIngestionLog instance or None.
    """
    try:
        log = DataIngestionLog.objects.create(
            source_name     = "sentiment_agent_rss",   # identifies Person 4's pipeline
            ticker          = company_name,            # CharField (plain string OK here)
            status          = status,
            error_message   = error_message,
            records_fetched = records_fetched,
        )
        logger.info(
            f"[write_ingestion_log] Logged: status={status}"
            f" records={records_fetched} for '{company_name}'"
        )
        return log
    except Exception as exc:
        logger.error(f"[write_ingestion_log] Failed: {exc}")
        return None

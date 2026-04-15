"""
rss_reader.py — Person 4 (Sentiment Agent)
==========================================
Fetches and filters RSS news feeds for a given company name.

This is a direct port of the Colab code into Django with the same
function names and variable names so you can recognise your own logic.

Functions:
  fetch_rss()                    — pulls all 12 RSS feeds, returns raw entries
  filter_news(entries, name)     — keyword match on title + summary
  remove_duplicates(entries)     — dedup by title+summary[:50] key
  build_text(entry)              — joins title + summary + published for FinBERT
"""

import logging
import feedparser  # pip install feedparser

logger = logging.getLogger(__name__)

# ─── RSS Feed Sources ─────────────────────────────────────────────────────────
# Kept exactly as in your Colab code — all 12 sources.

RSS_FEEDS = [
    "https://economictimes.indiatimes.com/rssfeeds/1977021501.cms",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.business-standard.com/rss/home_page_top_stories.rss",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.livemint.com/rss/markets",
    "https://www.livemint.com/rss/companies",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://finance.yahoo.com/rss/topstories",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.investing.com/rss/news.rss",
]

# ─── fetch_rss ────────────────────────────────────────────────────────────────

def fetch_rss() -> list:
    """
    Fetches all RSS_FEEDS and returns a flat list of all feed entries.

    Each entry is a feedparser dict-like object with keys:
      title, summary, published, link, etc.

    Errors on individual feeds are caught and logged — a broken feed
    will never stop the rest from being fetched (same behaviour as Colab).

    Returns
    -------
    list of feedparser entry objects
    """
    all_entries = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            all_entries.extend(feed.entries)
            logger.debug(f"Fetched {len(feed.entries)} entries from {url}")
        except Exception as e:
            # Matches original Colab error handling: print + continue
            logger.warning(f"Error fetching {url}: {e}")
    logger.info(f"Total RSS entries fetched: {len(all_entries)}")
    return all_entries


# ─── filter_news ─────────────────────────────────────────────────────────────

def filter_news(entries: list, company_name: str) -> list:
    """
    Filters entries to only those that mention the company name in
    title or summary (case-insensitive).

    This is identical to your Colab filter_news() logic.

    Parameters
    ----------
    entries     : list — raw entries from fetch_rss()
    company_name: str  — e.g. 'Tata Motors', 'Reliance Industries'

    Returns
    -------
    list of matching entries
    """
    filtered = []
    # Lowercase once (same as Colab)
    company_name_lower = company_name.lower()

    for entry in entries:
        title   = entry.get("title", "")
        summary = entry.get("summary", "")
        # Combine title + summary and search (same as Colab)
        text = (title + " " + summary).lower()
        if company_name_lower in text:
            filtered.append(entry)

    logger.info(
        f"[{company_name}] Filtered {len(filtered)} articles"
        f" from {len(entries)} total entries."
    )
    return filtered


# ─── remove_duplicates ───────────────────────────────────────────────────────

def remove_duplicates(entries: list) -> list:
    """
    Removes duplicate entries using title + summary[:50] as a composite key.

    Identical to your Colab remove_duplicates() logic.

    Parameters
    ----------
    entries : list — filtered entries from filter_news()

    Returns
    -------
    list with duplicates removed (preserves first occurrence)
    """
    seen   = set()
    unique = []
    for entry in entries:
        title   = entry.get("title", "").strip().lower()
        summary = entry.get("summary", "").strip().lower()
        # Composite key: full title + first 50 chars of summary
        key = title + summary[:50]
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    logger.debug(f"Deduplication: {len(entries)} → {len(unique)} entries.")
    return unique


# ─── build_text ──────────────────────────────────────────────────────────────

def build_text(entry) -> str:
    """
    Concatenates title + summary + published into a single string
    for FinBERT input.

    Identical to your Colab build_text() logic.

    Parameters
    ----------
    entry : feedparser entry object

    Returns
    -------
    str — formatted text ready for get_sentiment()
    """
    title     = entry.get("title", "")
    summary   = entry.get("summary", "")
    published = entry.get("published", "")
    # f-string matches Colab exactly
    return f"{title}. {summary}. {published}"

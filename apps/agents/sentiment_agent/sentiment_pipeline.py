"""
sentiment_pipeline.py — Person 4 (Sentiment Agent)
===================================================
Main pipeline function.  Accepts a company name, fetches news via RSS,
runs FinBERT on each article, aggregates scores, and returns a rich
result dict that everything else (db_writer, decision_rules, api_views)
consumes.

Entry point:
  run_pipeline(company_name: str) -> dict | None

The logic is a direct evolution of your Colab run_pipeline() with
the same flow — just extended to return the full result dict required
by the Django system instead of just the label string.
"""

import logging
from .rss_reader    import fetch_rss, filter_news, remove_duplicates, build_text
from .finbert_model import get_sentiment

logger = logging.getLogger(__name__)

# ─── Event-Risk Keywords ──────────────────────────────────────────────────────
# Architecture Rule 5: event_risk_flag is a hard override → band = CRITICAL

EVENT_RISK_KEYWORDS = [
    "fraud",
    "sebi",
    "investigation",
    "insolvency",
    "default",
    "promoter selling",
    "de-listing",
    "delisting",
    "scam",
    "penalty",
    "ban",
]

# ─── Score → Band mapping (Architecture Rule 8) ───────────────────────────────
# score = (sentiment_score + 1) * 50  maps  -1..+1  →  0..100
#   0–25   → CRITICAL
#  25–45   → HIGH
#  45–65   → MEDIUM
#  65–100  → LOW

def _score_to_band(score_0_to_100: float) -> str:
    """
    Converts a 0-100 numeric sentiment score to a categorical risk band.
    Lower score = more negative sentiment = higher risk band.
    """
    if score_0_to_100 < 25:
        return "CRITICAL"
    elif score_0_to_100 < 45:
        return "HIGH"
    elif score_0_to_100 < 65:
        return "MEDIUM"
    else:
        return "LOW"


# ─── aggregate_sentiment ─────────────────────────────────────────────────────

def aggregate_sentiment(results: list) -> tuple:
    """
    Aggregates a list of per-article FinBERT results into:
      - overall_sentiment : 'positive' / 'neutral' / 'negative'
      - sentiment_score   : float  -1 to +1
      - confidence        : float  0 to 1 (average FinBERT confidence)

    Logic is identical to your Colab aggregate_sentiment() — weighted
    average using label × confidence.  Thresholds: > 0.2 → positive,
    < -0.2 → negative, else neutral.

    Parameters
    ----------
    results : list of dicts, each with keys 'label' and 'score'

    Returns
    -------
    tuple  (overall_sentiment: str, sentiment_score: float, confidence: float)
    """
    score_map = {"positive": 1, "neutral": 0, "negative": -1}
    total       = 0.0
    conf_total  = 0.0
    count       = 0

    for r in results:
        label = r.get("label", "neutral")
        score = r.get("score", 0.0)
        if label in score_map:
            total      += score_map[label] * score
            conf_total += score
            count      += 1

    if count == 0:
        return "neutral", 0.0, 0.0

    avg        = total      / count   # weighted sentiment  -1..+1
    confidence = conf_total / count   # average FinBERT confidence

    if avg > 0.2:
        overall = "positive"
    elif avg < -0.2:
        overall = "negative"
    else:
        overall = "neutral"

    return overall, round(avg, 4), round(confidence, 4)


# ─── check_event_risk ────────────────────────────────────────────────────────

def check_event_risk(entries: list) -> bool:
    """
    Returns True if ANY headline in the article list contains one of the
    EVENT_RISK_KEYWORDS (case-insensitive).

    This is a hard override: if True → band is forced to CRITICAL
    regardless of the sentiment score.
    """
    for entry in entries:
        title   = entry.get("title", "").lower()
        summary = entry.get("summary", "").lower()
        text    = title + " " + summary
        for kw in EVENT_RISK_KEYWORDS:
            if kw in text:
                logger.warning(
                    f"Event risk keyword '{kw}' found in: {entry.get('title', '')[:80]}"
                )
                return True
    return False


# ─── run_pipeline  ────────────────────────────────────────────────────────────

def run_pipeline(company_name: str) -> dict | None:
    """
    Main pipeline function — Person 4's core contribution.

    Flow (same as Colab, extended):
      1. Fetch all RSS feeds
      2. Filter to articles mentioning company_name
      3. Remove duplicates
      4. Run FinBERT on up to 5 articles (same limit as Colab)
      5. Aggregate scores
      6. Compute event_risk_flag
      7. Map score → band (with event_risk override)
      8. Return full result dict

    Parameters
    ----------
    company_name : str  — e.g. 'Tata Motors', 'Reliance Industries'

    Returns
    -------
    dict  with keys:
        company_name      : str
        overall_sentiment : str   — 'positive' / 'negative' / 'neutral'
        sentiment_score   : float — -1 to +1
        confidence        : float — 0 to 1
        articles_analysed : int
        event_risk_flag   : bool
        band              : str   — 'LOW' / 'MEDIUM' / 'HIGH' / 'CRITICAL'
        top_headlines     : list[str]
        raw_sentiments    : list[dict]  — per-article FinBERT results
        processed_entries : list        — raw feedparser entries (for db_writer)

    Returns None if no articles were found for this company.
    """
    logger.info(f"[run_pipeline] Starting for: {company_name}")

    # Step 1 — Fetch all RSS feeds (same as Colab fetch_rss())
    entries = fetch_rss()

    # Step 2 — Filter to articles about this company (same as Colab filter_news())
    filtered = filter_news(entries, company_name)

    # Step 3 — Remove duplicates (same as Colab remove_duplicates())
    filtered = remove_duplicates(filtered)

    if not filtered:
        logger.warning(f"[run_pipeline] No articles found for '{company_name}'.")
        return None

    # Step 4 — Run FinBERT on up to 5 articles (same limit as Colab)
    sentiments = []
    processed_entries = []
    top_headlines = []

    for entry in filtered[:5]:    # [:5] matches Colab
        text      = build_text(entry)
        sentiment = get_sentiment(text)   # calls finbert_model.py
        sentiments.append(sentiment)
        processed_entries.append(entry)
        top_headlines.append(entry.get("title", "").strip())

    # Step 5 — Aggregate scores
    overall, sentiment_score, confidence = aggregate_sentiment(sentiments)

    # Step 6 — Check event risk flag (hard override)
    event_risk_flag = check_event_risk(processed_entries)

    # Step 7 — Map score → band
    # score = (sentiment_score + 1) * 50  maps -1..+1 → 0..100
    score_0_to_100 = (sentiment_score + 1) * 50
    band = _score_to_band(score_0_to_100)

    # Architecture Rule 5: event_risk_flag forces band = CRITICAL
    if event_risk_flag:
        band = "CRITICAL"
        logger.warning(
            f"[run_pipeline] event_risk_flag=True for '{company_name}'"
            f" — band forced to CRITICAL."
        )

    result = {
        "company_name"      : company_name,
        "overall_sentiment" : overall,
        "sentiment_score"   : sentiment_score,
        "confidence"        : confidence,
        "articles_analysed" : len(processed_entries),
        "event_risk_flag"   : event_risk_flag,
        "band"              : band,
        "score"             : round(score_0_to_100, 2),   # 0-100 for AgentOutput
        "top_headlines"     : top_headlines,
        "raw_sentiments"    : sentiments,                 # per-article FinBERT dicts
        "processed_entries" : processed_entries,          # feedparser entries for db_writer
    }

    logger.info(
        f"[run_pipeline] Done for '{company_name}': "
        f"sentiment={overall} score={sentiment_score:.3f} "
        f"band={band} event_risk={event_risk_flag}"
    )
    return result

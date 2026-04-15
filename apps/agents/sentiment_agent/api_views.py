"""
api_views.py — Person 4 (Sentiment Agent)
==========================================
DRF APIView for POST /api/sentiment/analyze/

This is the MAIN interface between Person 4's module and the rest of
the CRPMS system.  The Decision Agent and Person 5's Dashboard both
call this endpoint.

Flow inside the view (per company):
  1. Run sentiment_pipeline.run_pipeline(company_name)
  2. Fetch latest market_risk AgentOutput from Person 3 (if available)
  3. Run decision_rules.apply_rules(sentiment_result, market_risk_data)
  4. Write to DB: NewsArticle, AgentOutput, DecisionLog, DataIngestionLog
  5. Return the full result dict

Architecture Rule 6: FinBERT inference is NOT done inside this view.
  It runs in sentiment_pipeline.py.  The singleton was loaded at
  import time in finbert_model.py.

Auth note: DRF's default permission is IsAuthenticated (set in settings.py).
  AllowAny is used here for internal service-to-service calls.
  Adjust in production if needed.
"""

import logging
from rest_framework.views   import APIView
from rest_framework.response import Response
from rest_framework          import status
from rest_framework.permissions import AllowAny

from apps.portfolio.models import AgentOutput

from .sentiment_pipeline import run_pipeline
from .decision_rules     import apply_rules
from .db_writer          import (
    write_news_article,
    write_agent_output,
    write_decision_log,
    write_ingestion_log,
    _get_watchlist,        # internal helper — used to check Watchlist existence
)

logger = logging.getLogger(__name__)


class SentimentAnalysisView(APIView):
    """
    POST /api/sentiment/analyze/

    Request body:
        {"companies": ["Tata Motors", "Reliance Industries", "Infosys"]}

    Response:
        {
          "results": {
              "Tata Motors": {
                  "overall_sentiment": "negative",
                  "sentiment_score": -0.43,
                  "confidence": 0.81,
                  "articles_analysed": 5,
                  "event_risk_flag": false,
                  "band": "HIGH",
                  "action": "REDUCE",
                  "decision_confidence": 0.76,
                  "top_headlines": [...],
                  "warning": null         ← populated if Watchlist not found
              },
              ...
          }
        }
    """

    # Allow internal service-to-service calls without login.
    # Change to IsAuthenticated in production if needed.
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # ── 1. Validate request body ──────────────────────────────────────────
        companies = request.data.get("companies", [])

        if not companies or not isinstance(companies, list):
            return Response(
                {"error": "Request body must contain a non-empty 'companies' list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = {}

        for company_name in companies:
            company_name = str(company_name).strip()
            if not company_name:
                continue

            logger.info(f"[SentimentAnalysisView] Processing: '{company_name}'")

            # ── 2. Check if company exists in Watchlist ───────────────────────
            # If not found we still return sentiment result but skip DB writes
            watchlist_exists = _get_watchlist(company_name) is not None
            warning = None
            if not watchlist_exists:
                warning = (
                    f"'{company_name}' not found in Watchlist. "
                    f"Sentiment analysis ran but DB writes were skipped."
                )
                logger.warning(f"[SentimentAnalysisView] {warning}")

            # ── 3. Run sentiment pipeline ─────────────────────────────────────
            pipeline_result = None
            try:
                pipeline_result = run_pipeline(company_name)
            except Exception as exc:
                logger.error(
                    f"[SentimentAnalysisView] Pipeline error for '{company_name}': {exc}"
                )
                # Log failure to DataIngestionLog and move on
                write_ingestion_log(
                    company_name=company_name,
                    status="FAILED",
                    records_fetched=0,
                    error_message=str(exc),
                )
                results[company_name] = {
                    "error"  : f"Pipeline failed: {exc}",
                    "warning": warning,
                }
                continue

            # No articles found for this company in RSS feeds
            if pipeline_result is None:
                write_ingestion_log(
                    company_name=company_name,
                    status="PARTIAL",
                    records_fetched=0,
                    error_message="No articles found in RSS feeds.",
                )
                results[company_name] = {
                    "overall_sentiment" : "neutral",
                    "sentiment_score"   : 0.0,
                    "confidence"        : 0.0,
                    "articles_analysed" : 0,
                    "event_risk_flag"   : False,
                    "band"              : "MEDIUM",
                    "action"            : "HOLD",
                    "decision_confidence": 0.1,
                    "top_headlines"     : [],
                    "warning"           : f"No articles found for '{company_name}' in RSS feeds.",
                }
                continue

            # ── 4. Fetch latest market_risk AgentOutput from Person 3 ─────────
            # This is read-only — we never write to market_risk rows.
            market_risk_data = {}
            try:
                watchlist_obj = _get_watchlist(company_name)
                if watchlist_obj:
                    mr_output = (
                        AgentOutput.objects
                        .filter(
                            ticker     = watchlist_obj,
                            agent_name = AgentOutput.AgentName.MARKET_RISK,
                        )
                        .order_by("-timestamp")
                        .first()
                    )
                    if mr_output:
                        market_risk_data = {
                            "band"      : mr_output.band or "",
                            "score"     : mr_output.score,
                            # Person 3 may store confidence inside raw_data
                            "confidence": mr_output.raw_data.get("confidence", 1.0)
                                          if mr_output.raw_data else 1.0,
                        }
                        logger.info(
                            f"[SentimentAnalysisView] Market risk for '{company_name}':"
                            f" band={mr_output.band} score={mr_output.score}"
                        )
            except Exception as exc:
                logger.warning(
                    f"[SentimentAnalysisView] Could not fetch market risk for"
                    f" '{company_name}': {exc}"
                )

            # ── 5. Apply decision rules ───────────────────────────────────────
            decision = apply_rules(pipeline_result, market_risk_data)
            action             = decision["action"]
            decision_confidence = decision["confidence"]
            reasoning          = decision["reasoning"]

            # ── 6. Write to DB (only if Watchlist entry exists) ───────────────
            if watchlist_exists:
                # Write one NewsArticle per processed entry
                for i, entry in enumerate(pipeline_result.get("processed_entries", [])):
                    raw_sent = pipeline_result.get("raw_sentiments", [])
                    art_sentiment = raw_sent[i] if i < len(raw_sent) else {"label": "neutral", "score": 0.0}
                    write_news_article(company_name, entry, art_sentiment)

                # Write AgentOutput (agent_name='sentiment')
                write_agent_output(company_name, pipeline_result)

                # Write DecisionLog
                write_decision_log(
                    company_name     = company_name,
                    action           = action,
                    confidence       = decision_confidence,
                    pipeline_result  = pipeline_result,
                    market_risk_data = market_risk_data,
                )

            # Write DataIngestionLog (always — Architecture Rule 3)
            write_ingestion_log(
                company_name    = company_name,
                status          = "SUCCESS",
                records_fetched = pipeline_result.get("articles_analysed", 0),
            )

            # ── 7. Build response for this company ────────────────────────────
            results[company_name] = {
                "overall_sentiment"  : pipeline_result["overall_sentiment"],
                "sentiment_score"    : pipeline_result["sentiment_score"],
                "confidence"         : pipeline_result["confidence"],
                "articles_analysed"  : pipeline_result["articles_analysed"],
                "event_risk_flag"    : pipeline_result["event_risk_flag"],
                "band"               : pipeline_result["band"],
                "action"             : action,
                "decision_confidence": decision_confidence,
                "reasoning"          : reasoning,
                "top_headlines"      : pipeline_result["top_headlines"],
                "warning"            : warning,
            }

        return Response({"results": results}, status=status.HTTP_200_OK)

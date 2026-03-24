"""
apps/portfolio/capital_filter.py

Helper classes used internally by Portfolio Agent Mode 2.

  CapitalFilter     — Filters the watchlist down to viable investment
                      candidates by risk band and price availability.

  OpportunityScorer — Scores and ranks those candidates by opportunity
                      quality, combining feature-engine scores with
                      real-time sentiment agent outputs.
"""

import logging
from typing import Optional

from apps.portfolio.models import AgentOutput, FeatureSnapshot, PriceHistory
from utils.cache import get_agent_output

logger = logging.getLogger('apps.portfolio')

# Risk bands considered safe for new capital deployment
_SAFE_BANDS = {'LOW', 'MEDIUM'}

# Band ordering for sort priority (lower index = ranked first)
_BAND_ORDER = {'LOW': 0, 'MEDIUM': 1}

# Fallback opportunity threshold when the primary minimum yields too few picks
_FALLBACK_MIN_OPPORTUNITY = 25.0


# ---------------------------------------------------------------------------
# CapitalFilter
# ---------------------------------------------------------------------------

class CapitalFilter:
    """
    Filters tickers from SectorMapping to only viable investment candidates.

    Applies two sequential filters:
      1. Risk band filter — drops tickers with HIGH or CRITICAL market-risk scores.
      2. Price availability filter — drops tickers with no recent price data.

    Both filters are non-raising; skipped tickers are logged at WARNING level.
    Summary counts are logged at INFO level after each filter pass.
    """

    # ── filter_by_risk ──────────────────────────────────────────────────────

    def filter_by_risk(self, tickers: list[str]) -> list[dict]:
        """
        Filters tickers to LOW and MEDIUM risk only.

        For each ticker, reads the latest ``market_risk`` AgentOutput first
        from Redis cache, then falls back to the DB if the cache misses.
        Tickers with no data at all are skipped with a WARNING log.

        Args:
            tickers: List of ticker symbols to evaluate.

        Returns:
            List of dicts — one per accepted ticker — ordered LOW band first,
            then MEDIUM, sorted by ``score`` ascending within each band::

                [
                    {'ticker': str, 'band': str, 'score': float, 'raw_output': dict},
                    ...
                ]
        """
        candidates: list[dict] = []
        skipped = 0

        for ticker in tickers:
            try:
                # 1. Try Redis cache first
                cached = get_agent_output('market_risk', ticker)

                if cached:
                    band  = cached.get('band', '')
                    score = cached.get('score', 0.0)
                    raw   = cached
                else:
                    # 2. Fall back to DB
                    record = (
                        AgentOutput.objects
                        .filter(
                            ticker__ticker=ticker,
                            agent_name=AgentOutput.AgentName.MARKET_RISK,
                        )
                        .order_by('-timestamp')
                        .first()
                    )
                    if record is None:
                        logger.warning(
                            'filter_by_risk: no market_risk data for %s — skipping', ticker
                        )
                        skipped += 1
                        continue

                    band  = record.band or ''
                    score = record.score
                    raw   = {'band': band, 'score': score, 'flags': record.flags}

                # 3. Apply band filter
                if band in _SAFE_BANDS:
                    logger.debug(
                        'filter_by_risk: ACCEPTED %s (band=%s score=%.2f)', ticker, band, score
                    )
                    candidates.append({
                        'ticker':     ticker,
                        'band':       band,
                        'score':      float(score),
                        'raw_output': raw,
                    })
                else:
                    logger.debug(
                        'filter_by_risk: REJECTED %s (band=%s score=%.2f)', ticker, band, score
                    )

            except Exception as exc:
                logger.error('filter_by_risk: unexpected error for %s: %s', ticker, exc)
                skipped += 1

        # Sort: LOW before MEDIUM, ascending score within band
        candidates.sort(key=lambda c: (_BAND_ORDER.get(c['band'], 99), c['score']))

        logger.info(
            'filter_by_risk: %d tickers → %d candidates (%d skipped)',
            len(tickers), len(candidates), skipped,
        )
        return candidates

    # ── get_current_price ───────────────────────────────────────────────────

    def get_current_price(self, ticker: str) -> Optional[float]:
        """
        Gets the latest closing price for a ticker from PriceHistory.

        Args:
            ticker: Ticker symbol (e.g. ``'TCS.NS'``).

        Returns:
            Latest close as a ``float``, or ``None`` if no record exists.
        """
        try:
            record = (
                PriceHistory.objects
                .filter(ticker__ticker=ticker)
                .order_by('-date')
                .first()
            )
            if record is None:
                return None
            return float(record.close)
        except Exception as exc:
            logger.error('get_current_price: error fetching price for %s: %s', ticker, exc)
            return None

    # ── filter_by_price_availability ────────────────────────────────────────

    def filter_by_price_availability(self, candidates: list[dict]) -> list[dict]:
        """
        Removes candidates that have no available price data.

        Calls :meth:`get_current_price` for each candidate. Tickers returning
        ``None`` are dropped with a WARNING log. Accepted candidates have a
        ``'current_price'`` key added in-place.

        Args:
            candidates: List of candidate dicts produced by :meth:`filter_by_risk`.

        Returns:
            Filtered list; each dict now contains ``'current_price': float``.
        """
        accepted: list[dict] = []
        dropped = 0

        for candidate in candidates:
            ticker = candidate['ticker']
            try:
                price = self.get_current_price(ticker)
                if price is None:
                    logger.warning(
                        'filter_by_price_availability: no price data for %s — removing', ticker
                    )
                    dropped += 1
                else:
                    logger.debug(
                        'filter_by_price_availability: %s price=%.4f', ticker, price
                    )
                    accepted.append({**candidate, 'current_price': price})
            except Exception as exc:
                logger.error(
                    'filter_by_price_availability: error for %s: %s', ticker, exc
                )
                dropped += 1

        logger.info(
            'filter_by_price_availability: %d candidates → %d with prices (%d dropped)',
            len(candidates), len(accepted), dropped,
        )
        return accepted


# ---------------------------------------------------------------------------
# OpportunityScorer
# ---------------------------------------------------------------------------

class OpportunityScorer:
    """
    Scores and ranks investment candidates by opportunity quality.

    Combines two signal sources into a single composite score:
      - ``opportunity_score`` (60 % weight) — from the feature engine's
        ``FeatureSnapshot.opportunity_features`` JSON field.
      - ``sentiment_score``   (40 % weight) — from the ``sentiment`` agent
        output (Redis cache → DB fallback).

    Both signals default to 50.0 when data is unavailable, keeping the
    composite score meaningful even with partial data.
    """

    # ── score_candidates ────────────────────────────────────────────────────

    def score_candidates(self, candidates: list[dict]) -> list[dict]:
        """
        Adds ``opportunity_score``, ``sentiment_score``, and ``composite_score``
        to each candidate dict.

        Scoring formula::

            composite = (opportunity_score × 0.6) + (sentiment_score × 0.4)

        Args:
            candidates: List of candidate dicts (output of
                :meth:`CapitalFilter.filter_by_price_availability`).

        Returns:
            Same list with three score keys added to every dict.
        """
        scored: list[dict] = []

        for candidate in candidates:
            ticker = candidate['ticker']
            try:
                # ── Opportunity score from FeatureSnapshot ────────────────
                opportunity_score = 50.0
                try:
                    snapshot = (
                        FeatureSnapshot.objects
                        .filter(ticker__ticker=ticker)
                        .order_by('-date')
                        .first()
                    )
                    if snapshot:
                        opportunity_score = float(
                            snapshot.opportunity_features.get('opportunity_score', 50.0)
                        )
                        logger.debug(
                            'score_candidates: %s opportunity_score=%.2f (FeatureSnapshot)',
                            ticker, opportunity_score,
                        )
                    else:
                        logger.debug(
                            'score_candidates: %s no FeatureSnapshot — defaulting opportunity_score=50.0',
                            ticker,
                        )
                except Exception as snap_exc:
                    logger.error(
                        'score_candidates: FeatureSnapshot error for %s: %s', ticker, snap_exc
                    )

                # ── Sentiment score from agent cache ──────────────────────
                sentiment_score = 50.0
                try:
                    cached_sentiment = get_agent_output('sentiment', ticker)
                    if cached_sentiment:
                        sentiment_score = float(cached_sentiment.get('score', 50.0))
                        logger.debug(
                            'score_candidates: %s sentiment_score=%.2f (cache)',
                            ticker, sentiment_score,
                        )
                    else:
                        logger.debug(
                            'score_candidates: %s no sentiment cache — defaulting sentiment_score=50.0',
                            ticker,
                        )
                except Exception as sent_exc:
                    logger.error(
                        'score_candidates: sentiment cache error for %s: %s', ticker, sent_exc
                    )

                # ── Composite ─────────────────────────────────────────────
                composite_score = (opportunity_score * 0.6) + (sentiment_score * 0.4)

                logger.debug(
                    'score_candidates: %s composite=%.2f (opp=%.2f sent=%.2f)',
                    ticker, composite_score, opportunity_score, sentiment_score,
                )

                scored.append({
                    **candidate,
                    'opportunity_score': opportunity_score,
                    'sentiment_score':   sentiment_score,
                    'composite_score':   composite_score,
                })

            except Exception as exc:
                logger.error('score_candidates: unexpected error for %s: %s', ticker, exc)
                # Include candidate with neutral defaults so it isn't silently lost
                scored.append({
                    **candidate,
                    'opportunity_score': 50.0,
                    'sentiment_score':   50.0,
                    'composite_score':   50.0,
                })

        logger.info('score_candidates: scored %d candidates', len(scored))
        return scored

    # ── rank_and_select ─────────────────────────────────────────────────────

    def rank_and_select(
        self,
        candidates: list[dict],
        max_picks: int = 5,
        min_opportunity_score: float = 40.0,
    ) -> list[dict]:
        """
        Ranks candidates by ``composite_score`` and returns the top N.

        Algorithm:
          1. Filter: remove candidates where ``opportunity_score`` is below
             ``min_opportunity_score``.
          2. If fewer than 2 candidates survive, retry with a fallback
             threshold of ``25.0`` to avoid returning an empty result.
          3. Sort survivors descending by ``composite_score``.
          4. Return the top ``max_picks`` candidates.

        Args:
            candidates:           Scored list from :meth:`score_candidates`.
            max_picks:            Maximum number of candidates to return (default 5).
            min_opportunity_score: Minimum ``opportunity_score`` to pass the filter
                                  (default 40.0).

        Returns:
            Top ``max_picks`` candidates, sorted by ``composite_score`` descending.
        """
        try:
            # ── Primary filter pass ───────────────────────────────────────
            filtered = [
                c for c in candidates
                if c.get('opportunity_score', 0.0) >= min_opportunity_score
            ]
            logger.debug(
                'rank_and_select: primary filter (min=%.1f) → %d / %d candidates',
                min_opportunity_score, len(filtered), len(candidates),
            )

            # ── Fallback if too few survive ───────────────────────────────
            if len(filtered) < 2:
                logger.info(
                    'rank_and_select: fewer than 2 candidates after primary filter '
                    '(%.1f) — retrying with fallback threshold %.1f',
                    min_opportunity_score, _FALLBACK_MIN_OPPORTUNITY,
                )
                filtered = [
                    c for c in candidates
                    if c.get('opportunity_score', 0.0) >= _FALLBACK_MIN_OPPORTUNITY
                ]
                logger.debug(
                    'rank_and_select: fallback filter (min=%.1f) → %d candidates',
                    _FALLBACK_MIN_OPPORTUNITY, len(filtered),
                )

            # ── Sort and slice ────────────────────────────────────────────
            ranked = sorted(filtered, key=lambda c: c.get('composite_score', 0.0), reverse=True)
            selected = ranked[:max_picks]

            logger.info(
                'rank_and_select: %d candidates filtered → %d selected (max_picks=%d)',
                len(candidates), len(selected), max_picks,
            )
            return selected

        except Exception as exc:
            logger.error('rank_and_select: unexpected error: %s', exc)
            return []

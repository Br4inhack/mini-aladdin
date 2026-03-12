"""
apps/portfolio/capital_allocator.py

Implements risk-adjusted capital allocation for Portfolio Agent Mode 2.

The CapitalAllocator converts a ranked list of investment candidates into
a concrete, actionable allocation plan specifying exact share quantities
and rupee amounts, subject to position-size guardrails.
"""

import math
import logging
import copy
from typing import Optional

from apps.portfolio.models import Watchlist

logger = logging.getLogger('apps.portfolio')


class CapitalAllocator:
    """
    Implements risk-adjusted capital allocation across selected tickers.

    Allocates available capital proportional to each stock's LOW-risk
    probability (extracted from the market-risk agent output). Enforces
    hard position-size limits and returns exact share quantities so the
    result can be passed directly to order creation.

    Class-level constraints
    -----------------------
    MAX_POSITION_PCT : float
        No single stock may receive more than 35 % of available capital.
    MIN_POSITION_PCT : float
        Stocks receiving less than 5 % are dropped from the allocation.
    DEFAULT_MIN_SHARES : int
        A stock is only included if at least 1 share can be purchased.

    Example
    -------
    >>> allocator = CapitalAllocator()
    >>> result = allocator.allocate(candidates, available_capital=500_000)
    >>> warnings = allocator.validate_allocation(result)
    """

    MAX_POSITION_PCT: float = 0.35
    MIN_POSITION_PCT: float = 0.05
    DEFAULT_MIN_SHARES: int = 1

    # ── allocate ────────────────────────────────────────────────────────────

    def allocate(self, candidates: list[dict], available_capital: float) -> dict:
        """
        Main allocation method. Returns a full rupee + share allocation plan.

        Works on a deep copy of ``candidates`` so the caller's list is never
        mutated. Follows six steps:

        1.  Extract raw LOW-risk probabilities as weights.
        2.  Normalise weights to sum to 1.0.
        3.  Enforce MAX / MIN position limits (up to 10 iterations).
        4.  Compute rupee amounts.
        5.  Compute share quantities; remove tickers where shares == 0.
        6.  Compute summary totals.

        If no risk-probability data is available across all candidates,
        falls back to :meth:`_equal_weight_fallback`.

        Args:
            candidates (list[dict]): Scored candidates from
                ``OpportunityScorer.rank_and_select()``. Each dict must
                contain at minimum ``ticker``, ``current_price``,
                ``raw_output``, ``band``, ``score``,
                ``opportunity_score``, and ``composite_score``.
            available_capital (float): Total rupee capital available for
                deployment (e.g. ``500000.0``).

        Returns:
            dict: Allocation plan with keys ``'allocations'`` and
            ``'summary'``. See module docstring for full schema.

        Example
        -------
        >>> result = allocator.allocate(candidates, 500_000)
        >>> result['summary']['deployment_pct']
        94.7
        """
        if not candidates:
            logger.warning('allocate: received empty candidates list — returning empty plan')
            return self._empty_result(available_capital)

        # Never mutate the caller's list
        pool = copy.deepcopy(candidates)

        # ── Step 1: Extract weights ─────────────────────────────────────────
        logger.debug('allocate: Step 1 — extracting risk weights for %d candidates', len(pool))

        all_fallback = True
        for c in pool:
            prob = (
                c.get('raw_output', {})
                 .get('probabilities', {})
                 .get('LOW', None)
            )
            if prob is not None:
                c['_weight'] = float(prob)
                all_fallback = False
                logger.debug('allocate: %s LOW-prob weight=%.4f', c['ticker'], prob)
            else:
                c['_weight'] = 0.5
                logger.debug('allocate: %s no LOW-prob — fallback weight=0.5', c['ticker'])

        if all_fallback:
            logger.info('allocate: no risk-probability data available — using equal-weight fallback')
            return self._equal_weight_fallback(candidates, available_capital)

        # ── Step 2: Normalise ───────────────────────────────────────────────
        pool = self._normalise(pool)
        logger.debug('allocate: Step 2 — normalised weights: %s',
                     {c['ticker']: round(c['_norm_weight'], 4) for c in pool})

        # ── Step 3: Enforce position limits (max 10 iterations) ────────────
        logger.debug('allocate: Step 3 — enforcing position limits (max=%.0f%%, min=%.0f%%)',
                     self.MAX_POSITION_PCT * 100, self.MIN_POSITION_PCT * 100)

        for iteration in range(10):
            changed = False

            # Cap any ticker exceeding MAX_POSITION_PCT
            excess_total = 0.0
            capped_indices = set()
            for i, c in enumerate(pool):
                if c['_norm_weight'] > self.MAX_POSITION_PCT:
                    excess = c['_norm_weight'] - self.MAX_POSITION_PCT
                    excess_total += excess
                    c['_norm_weight'] = self.MAX_POSITION_PCT
                    capped_indices.add(i)
                    changed = True
                    logger.debug(
                        'allocate: iter=%d capped %s, excess=%.4f', iteration, c['ticker'], excess
                    )

            # Redistribute excess to uncapped tickers
            if excess_total > 0 and capped_indices:
                free = [c for i, c in enumerate(pool) if i not in capped_indices]
                if free:
                    share = excess_total / len(free)
                    for c in free:
                        c['_norm_weight'] += share

            # Drop any ticker below MIN_POSITION_PCT
            before = len(pool)
            pool = [c for c in pool if c['_norm_weight'] >= self.MIN_POSITION_PCT]
            dropped = before - len(pool)
            if dropped:
                changed = True
                logger.debug('allocate: iter=%d dropped %d sub-minimum tickers', iteration, dropped)
                pool = self._normalise(pool)

            if not changed:
                logger.debug('allocate: Step 3 converged after %d iteration(s)', iteration + 1)
                break
        else:
            logger.warning('allocate: position-limit loop hit max 10 iterations — proceeding')
            pool = self._normalise(pool)

        if not pool:
            logger.warning('allocate: all candidates removed during limit enforcement')
            return self._empty_result(available_capital)

        # ── Step 4: Compute rupee amounts ───────────────────────────────────
        logger.debug('allocate: Step 4 — computing rupee amounts')
        for c in pool:
            c['_rupee_amount'] = round(c['_norm_weight'] * available_capital, 2)
            logger.debug('allocate: %s rupee_amount=%.2f', c['ticker'], c['_rupee_amount'])

        # ── Step 5: Compute share quantities ────────────────────────────────
        logger.debug('allocate: Step 5 — computing share quantities')
        viable = []
        for c in pool:
            price = c.get('current_price', 0.0)
            if not price or price <= 0:
                logger.warning('allocate: %s has zero/invalid price — skipping', c['ticker'])
                continue
            shares = math.floor(c['_rupee_amount'] / price)
            if shares < self.DEFAULT_MIN_SHARES:
                logger.warning(
                    'allocate: %s cannot buy even 1 share (price=%.2f, budget=%.2f) — removing',
                    c['ticker'], price, c['_rupee_amount'],
                )
                continue
            c['_shares']       = shares
            c['_actual_rupees'] = round(shares * price, 2)
            viable.append(c)

        # If tickers were removed, recalculate percentages from actual rupees
        if len(viable) < len(pool):
            logger.info('allocate: recalculating after %d zero-share removals', len(pool) - len(viable))

        # ── Step 6: Compute totals ──────────────────────────────────────────
        total_deployed  = round(sum(c['_actual_rupees'] for c in viable), 2)
        leftover        = round(available_capital - total_deployed, 2)
        deployment_pct  = round((total_deployed / available_capital) * 100, 2) if available_capital else 0.0

        # Fetch company_name and sector from Watchlist in a single query
        ticker_symbols  = [c['ticker'] for c in viable]
        wl_map          = {
            w.ticker: w
            for w in Watchlist.objects.filter(ticker__in=ticker_symbols).only('ticker', 'company_name', 'sector')
        }

        allocations = []
        for c in viable:
            wl = wl_map.get(c['ticker'])
            actual_rupees = c['_actual_rupees']
            alloc_pct = round((actual_rupees / available_capital) * 100, 2) if available_capital else 0.0
            allocations.append({
                'ticker':            c['ticker'],
                'company_name':      wl.company_name if wl else '',
                'sector':            wl.sector if wl else c.get('sector', ''),
                'shares':            c['_shares'],
                'current_price':     round(c['current_price'], 2),
                'rupee_amount':      actual_rupees,
                'allocation_pct':    alloc_pct,
                'risk_band':         c.get('band', ''),
                'risk_score':        round(c.get('score', 0.0), 4),
                'opportunity_score': round(c.get('opportunity_score', 0.0), 2),
                'composite_score':   round(c.get('composite_score', 0.0), 2),
            })

        sectors_covered = sorted({a['sector'] for a in allocations if a['sector']})

        logger.info(
            'allocate: deployed ₹%.2f / ₹%.2f (%.1f%%) across %d positions in %d sector(s)',
            total_deployed, available_capital, deployment_pct, len(allocations), len(sectors_covered),
        )

        return {
            'allocations': allocations,
            'summary': {
                'total_available':  round(available_capital, 2),
                'total_deployed':   total_deployed,
                'leftover_capital': leftover,
                'deployment_pct':   deployment_pct,
                'num_positions':    len(allocations),
                'sectors_covered':  sectors_covered,
            },
        }

    # ── _equal_weight_fallback ──────────────────────────────────────────────

    def _equal_weight_fallback(self, candidates: list[dict], available_capital: float) -> dict:
        """
        Fallback allocator when no risk-probability data is available.

        Splits ``available_capital`` equally across all candidates and
        computes share quantities at equal weight. Returns the same dict
        structure as :meth:`allocate`.

        Args:
            candidates (list[dict]): Candidate dicts with at minimum
                ``ticker`` and ``current_price``.
            available_capital (float): Total rupee capital to deploy.

        Returns:
            dict: Allocation plan (same schema as :meth:`allocate`).

        Example
        -------
        >>> result = allocator._equal_weight_fallback(candidates, 200_000)
        >>> result['summary']['num_positions']
        5
        """
        pool = copy.deepcopy(candidates)
        if not pool:
            return self._empty_result(available_capital)

        equal_weight = 1.0 / len(pool)
        for c in pool:
            c['_norm_weight']   = equal_weight
            c['_rupee_amount']  = round(equal_weight * available_capital, 2)

        viable = []
        for c in pool:
            price = c.get('current_price', 0.0)
            if not price or price <= 0:
                continue
            shares = math.floor(c['_rupee_amount'] / price)
            if shares < self.DEFAULT_MIN_SHARES:
                logger.warning(
                    '_equal_weight_fallback: %s cannot buy 1 share — skipping', c['ticker']
                )
                continue
            c['_shares']        = shares
            c['_actual_rupees'] = round(shares * price, 2)
            viable.append(c)

        total_deployed = round(sum(c['_actual_rupees'] for c in viable), 2)
        leftover       = round(available_capital - total_deployed, 2)
        deployment_pct = round((total_deployed / available_capital) * 100, 2) if available_capital else 0.0

        ticker_symbols = [c['ticker'] for c in viable]
        wl_map = {
            w.ticker: w
            for w in Watchlist.objects.filter(ticker__in=ticker_symbols).only('ticker', 'company_name', 'sector')
        }

        allocations = []
        for c in viable:
            wl = wl_map.get(c['ticker'])
            actual_rupees = c['_actual_rupees']
            alloc_pct = round((actual_rupees / available_capital) * 100, 2) if available_capital else 0.0
            allocations.append({
                'ticker':            c['ticker'],
                'company_name':      wl.company_name if wl else '',
                'sector':            wl.sector if wl else '',
                'shares':            c['_shares'],
                'current_price':     round(c['current_price'], 2),
                'rupee_amount':      actual_rupees,
                'allocation_pct':    alloc_pct,
                'risk_band':         c.get('band', ''),
                'risk_score':        round(c.get('score', 0.0), 4),
                'opportunity_score': round(c.get('opportunity_score', 0.0), 2),
                'composite_score':   round(c.get('composite_score', 0.0), 2),
            })

        sectors_covered = sorted({a['sector'] for a in allocations if a['sector']})

        logger.info(
            '_equal_weight_fallback: deployed ₹%.2f across %d positions (equal weight)',
            total_deployed, len(allocations),
        )

        return {
            'allocations': allocations,
            'summary': {
                'total_available':  round(available_capital, 2),
                'total_deployed':   total_deployed,
                'leftover_capital': leftover,
                'deployment_pct':   deployment_pct,
                'num_positions':    len(allocations),
                'sectors_covered':  sectors_covered,
            },
        }

    # ── validate_allocation ─────────────────────────────────────────────────

    def validate_allocation(self, allocation_result: dict) -> list[str]:
        """
        Validates an allocation result and returns a list of warning strings.

        Checks four risk/quality conditions. Returns an empty list when the
        allocation is clean.

        Args:
            allocation_result (dict): Output from :meth:`allocate` or
                :meth:`_equal_weight_fallback`.

        Returns:
            list[str]: Zero or more warning strings, each prefixed with
            ``'WARNING: '``.

        Example
        -------
        >>> warnings = allocator.validate_allocation(result)
        >>> for w in warnings:
        ...     print(w)
        WARNING: Only 45.2% of capital deployed — low utilisation
        """
        warnings: list[str] = []
        allocations = allocation_result.get('allocations', [])
        summary     = allocation_result.get('summary', {})

        # 1. Position concentration
        for a in allocations:
            if a['allocation_pct'] > self.MAX_POSITION_PCT * 100:
                warnings.append(
                    f"WARNING: {a['ticker']} exceeds 35% position limit "
                    f"(actual {a['allocation_pct']:.1f}%)"
                )

        # 2. Diversification
        num_positions = summary.get('num_positions', len(allocations))
        if num_positions < 2:
            warnings.append('WARNING: Only 1 position — insufficient diversification')

        # 3. Sector concentration
        sectors = {a['sector'] for a in allocations if a['sector']}
        if len(sectors) == 1 and num_positions > 1:
            warnings.append(
                f"WARNING: All positions in same sector ({next(iter(sectors))}) "
                f"— sector concentration risk"
            )

        # 4. Low capital utilisation
        deployment_pct = summary.get('deployment_pct', 100.0)
        if deployment_pct < 80.0:
            warnings.append(
                f"WARNING: Only {deployment_pct:.1f}% of capital deployed — low utilisation"
            )

        if warnings:
            logger.warning('validate_allocation: %d warning(s) generated', len(warnings))
        else:
            logger.info('validate_allocation: allocation is clean — no warnings')

        return warnings

    # ── Private helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _normalise(pool: list[dict]) -> list[dict]:
        """Re-normalise ``_norm_weight`` fields so they sum to exactly 1.0."""
        total = sum(c['_weight'] if '_norm_weight' not in c else c['_norm_weight'] for c in pool)
        if total == 0:
            equal = 1.0 / len(pool) if pool else 0.0
            for c in pool:
                c['_norm_weight'] = equal
        else:
            for c in pool:
                raw = c.get('_norm_weight', c.get('_weight', 0.0))
                c['_norm_weight'] = raw / total
        return pool

    @staticmethod
    def _empty_result(available_capital: float) -> dict:
        """Returns a zeroed-out allocation result when no positions can be taken."""
        return {
            'allocations': [],
            'summary': {
                'total_available':  round(available_capital, 2),
                'total_deployed':   0.0,
                'leftover_capital': round(available_capital, 2),
                'deployment_pct':   0.0,
                'num_positions':    0,
                'sectors_covered':  [],
            },
        }

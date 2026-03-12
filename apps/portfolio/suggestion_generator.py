"""
apps/portfolio/suggestion_generator.py

Converts allocation results and agent decisions into natural language text
the user can read and act on.

  Phase 1: generate_mode1_suggestion — enhanced single-ticker action suggestion
  Phase 2: generate_mode2_suggestion — multi-paragraph fresh-capital deployment plan
  Phase 3: will replace both with Claude API calls (drop-in replacement)
"""

import logging
from typing import Optional

logger = logging.getLogger('apps.portfolio')


class SuggestionGenerator:
    """
    Generates human-readable portfolio suggestions from allocation data.

    Bridges the gap between the quantitative output of CapitalAllocator /
    DecisionEngine and the user-facing dashboard text. All methods return
    plain strings with paragraph breaks (double newlines). No external API
    dependencies — Phase 3 will hot-swap these methods with Claude calls.

    Example
    -------
    >>> sg = SuggestionGenerator()
    >>> text = sg.generate_mode2_suggestion(
    ...     available_capital=500_000,
    ...     preferred_sectors=['IT', 'Pharma'],
    ...     allocation_result=result,
    ...     warnings=warnings,
    ... )
    >>> print(text)
    """

    # ── Public: Mode 2 ──────────────────────────────────────────────────────

    def generate_mode2_suggestion(
        self,
        available_capital: float,
        preferred_sectors: list[str],
        allocation_result: dict,
        warnings: list[str],
    ) -> str:
        """
        Generates a complete natural language suggestion for fresh capital deployment.

        Produces exactly 4 paragraphs (Paragraph 4 omitted when warnings is empty):

        1. **Summary** — capital, sector preference, positions count, deployment amount.
        2. **Position breakdown** — one sentence per allocation with price and scores.
        3. **Risk context** — band summary, highest-risk position, diversification comment.
        4. **Warnings** — only rendered when ``warnings`` is non-empty.

        Args:
            available_capital (float): Total rupee capital available to deploy.
            preferred_sectors (list[str]): User's stated sector preferences
                (e.g. ``['IT', 'Pharma']``).
            allocation_result (dict): Output from ``CapitalAllocator.allocate()``.
            warnings (list[str]): Output from ``CapitalAllocator.validate_allocation()``.

        Returns:
            str: Multi-paragraph suggestion text, paragraphs separated by
            ``'\\n\\n'``. Returns an error string on unexpected failure.

        Example
        -------
        >>> sg = SuggestionGenerator()
        >>> text = sg.generate_mode2_suggestion(500_000, ['IT'], result, [])
        >>> assert text.startswith('Based on your available capital')
        """
        try:
            allocations   = allocation_result.get('allocations', [])
            summary       = allocation_result.get('summary', {})
            total_deployed  = summary.get('total_deployed', 0.0)
            leftover        = summary.get('leftover_capital', 0.0)
            deployment_pct  = summary.get('deployment_pct', 0.0)
            num_positions   = summary.get('num_positions', len(allocations))
            sectors_covered = summary.get('sectors_covered', [])

            # ── Paragraph 1 — Summary ─────────────────────────────────────
            sector_list          = self._format_sector_list(preferred_sectors)
            sectors_covered_count = len(sectors_covered)

            para1 = (
                f"Based on your available capital of ₹{available_capital:,.0f} and your "
                f"preference for {sector_list} stocks, we have identified {num_positions} "
                f"investment opportunit{'y' if num_positions == 1 else 'ies'} across "
                f"{sectors_covered_count} sector(s). A total of ₹{total_deployed:,.0f} "
                f"({deployment_pct:.1f}%) will be deployed, with ₹{leftover:,.0f} remaining "
                f"as available capital due to share lot sizing."
            )
            logger.debug('generate_mode2_suggestion: paragraph 1 built')

            # ── Paragraph 2 — Position breakdown ─────────────────────────
            if allocations:
                position_lines = []
                for a in allocations:
                    line = (
                        f"{a.get('company_name', a['ticker'])} ({a['ticker']}) "
                        f"— {a.get('sector', '—')}: "
                        f"Buy {a['shares']} share{'s' if a['shares'] != 1 else ''} "
                        f"at ₹{a['current_price']:,.2f} each, "
                        f"deploying ₹{a['rupee_amount']:,.0f} "
                        f"({a['allocation_pct']:.1f}% of capital). "
                        f"Current risk classification: {a.get('risk_band', '—')}. "
                        f"Opportunity score: {a.get('opportunity_score', 0):.0f}/100."
                    )
                    position_lines.append(line)
                para2 = '\n'.join(position_lines)
            else:
                para2 = 'No positions could be allocated with the current capital and risk parameters.'

            logger.debug('generate_mode2_suggestion: paragraph 2 built (%d lines)', len(allocations))

            # ── Paragraph 3 — Risk context ────────────────────────────────
            risk_summary = self._get_risk_summary(allocations)

            # Highest risk position = highest risk_score
            if allocations:
                highest = max(allocations, key=lambda a: a.get('risk_score', 0.0))
                highest_ticker = highest['ticker']
                highest_score  = highest.get('risk_score', 0.0) * 100  # score stored 0-1 → 0-100
            else:
                highest_ticker = '—'
                highest_score  = 0.0

            # Sector concentration comment
            unique_sectors = {a.get('sector', '') for a in allocations if a.get('sector')}
            if len(unique_sectors) == 1:
                only_sector = next(iter(unique_sectors))
                sector_concentration_comment = (
                    f"Note: All positions are in {only_sector} — consider diversifying "
                    f"across sectors in future deployments."
                )
            else:
                sector_concentration_comment = (
                    f"Your capital is spread across {len(unique_sectors)} sectors, "
                    f"providing good diversification."
                )

            para3 = (
                f"All selected stocks are currently classified as {risk_summary}. "
                f"The highest risk position is {highest_ticker} with a score of "
                f"{highest_score:.0f}/100. "
                f"{sector_concentration_comment}"
            )
            logger.debug('generate_mode2_suggestion: paragraph 3 built')

            # ── Paragraph 4 — Warnings (conditional) ─────────────────────
            paragraphs = [para1, para2, para3]

            if warnings:
                para4 = 'Considerations: ' + '. '.join(
                    # Strip leading 'WARNING: ' prefix for cleaner prose
                    w.replace('WARNING: ', '') for w in warnings
                )
                paragraphs.append(para4)
                logger.debug('generate_mode2_suggestion: paragraph 4 built (%d warnings)', len(warnings))

            logger.info(
                'generate_mode2_suggestion: generated %d-paragraph suggestion '
                'for %d positions, ₹%.0f deployed',
                len(paragraphs), num_positions, total_deployed,
            )

            return '\n\n'.join(paragraphs)

        except Exception as exc:
            logger.error('generate_mode2_suggestion: unexpected error: %s', exc)
            return (
                f"Unable to generate suggestion at this time. "
                f"Please review the allocation data manually. (Error: {exc})"
            )

    # ── Public: Mode 1 ──────────────────────────────────────────────────────

    def generate_mode1_suggestion(
        self,
        ticker: str,
        action: str,
        decision_data: dict,
        agent_outputs: dict,
    ) -> str:
        """
        Enhanced Phase 1 template — richer 2-paragraph action suggestion
        for a single-ticker decision.

        Upgraded from Phase 1 single-line templates. Phase 3 will replace
        this with a Claude API call using the same signature.

        Args:
            ticker (str): Ticker symbol being acted on (e.g. ``'TCS.NS'``).
            action (str): Decision engine action — one of ``HOLD``, ``REDUCE``,
                ``EXIT``, ``INCREASE``, or ``REALLOCATE``.
            decision_data (dict): Dict with keys ``confidence_score``,
                ``current_qty`` (int), ``current_price`` (float),
                ``current_pct`` (float, 0-100), ``target_pct`` (float, 0-100).
            agent_outputs (dict): Dict keyed by agent name
                (``market_risk``, ``sentiment``) containing agent output dicts
                with ``score`` and ``band`` keys.

        Returns:
            str: Two-paragraph suggestion string separated by ``'\\n\\n'``.
            Returns an error string on unexpected failure.

        Example
        -------
        >>> text = sg.generate_mode1_suggestion(
        ...     'TCS.NS', 'REDUCE', decision_data, agent_outputs
        ... )
        >>> assert 'REDUCE' in text or 'reduce' in text.lower()
        """
        try:
            action_upper = action.upper().strip()

            # Extract context values with safe defaults
            confidence_pct  = round(decision_data.get('confidence_score', 0.0) * 100, 1)
            current_qty     = int(decision_data.get('current_qty', 0))
            current_price   = float(decision_data.get('current_price', 0.0))
            current_pct     = float(decision_data.get('current_pct', 0.0))
            target_pct      = float(decision_data.get('target_pct', 20.0))

            risk_output      = agent_outputs.get('market_risk', {}) or {}
            sentiment_output = agent_outputs.get('sentiment', {}) or {}

            risk_score    = float(risk_output.get('score', 0.0)) * 100
            risk_band     = risk_output.get('band', '—')
            sentiment_raw = float(sentiment_output.get('score', 50.0))
            # Normalise sentiment if stored 0-1; keep if already 0-100
            sentiment_score = sentiment_raw * 100 if sentiment_raw <= 1.0 else sentiment_raw

            # ── Paragraph 1 — What the system recommends and why ─────────
            action_templates = {
                'HOLD': (
                    f"The CRPMS system recommends holding your current position in {ticker}. "
                    f"The market risk score is {risk_score:.0f}/100 ({risk_band} band), "
                    f"and sentiment is tracking at {sentiment_score:.0f}/100. "
                    f"The decision engine has {confidence_pct:.1f}% confidence in this recommendation."
                ),
                'REDUCE': (
                    f"The CRPMS system recommends reducing your position in {ticker}. "
                    f"The market risk score has risen to {risk_score:.0f}/100 ({risk_band} band), "
                    f"signalling elevated exposure. Sentiment stands at {sentiment_score:.0f}/100. "
                    f"Decision confidence: {confidence_pct:.1f}%."
                ),
                'EXIT': (
                    f"The CRPMS system recommends exiting your full position in {ticker} immediately. "
                    f"The market risk score is {risk_score:.0f}/100 ({risk_band} band) — "
                    f"above the critical threshold. Sentiment is {sentiment_score:.0f}/100. "
                    f"Decision confidence: {confidence_pct:.1f}%."
                ),
                'INCREASE': (
                    f"The CRPMS system recommends increasing your position in {ticker}. "
                    f"Risk is currently {risk_score:.0f}/100 ({risk_band} band) and "
                    f"sentiment is strong at {sentiment_score:.0f}/100. "
                    f"Decision confidence: {confidence_pct:.1f}%."
                ),
                'REALLOCATE': (
                    f"The CRPMS system recommends reallocating capital away from {ticker}. "
                    f"While risk is {risk_score:.0f}/100 ({risk_band}), the opportunity score "
                    f"has declined and higher-quality alternatives are available. "
                    f"Decision confidence: {confidence_pct:.1f}%."
                ),
            }
            para1 = action_templates.get(
                action_upper,
                f"The CRPMS system has flagged {ticker} for review "
                f"(action: {action_upper}, confidence: {confidence_pct:.1f}%)."
            )

            # ── Paragraph 2 — What to do specifically ────────────────────
            if action_upper == 'HOLD':
                para2 = 'No action needed. Continue to monitor daily.'

            elif action_upper == 'REDUCE':
                reduce_qty   = self._compute_reduce_quantity(
                    current_qty, current_pct, target_pct, current_price
                )
                freed_capital = round(reduce_qty * current_price, 2)
                para2 = (
                    f"Consider selling {reduce_qty} share{'s' if reduce_qty != 1 else ''} "
                    f"to bring allocation to safe levels. "
                    f"This frees approximately ₹{freed_capital:,.0f} in capital."
                )

            elif action_upper == 'EXIT':
                para2 = (
                    f"Exit your full position of {current_qty} "
                    f"share{'s' if current_qty != 1 else ''} as soon as possible. "
                    f"This is a time-sensitive recommendation."
                )

            elif action_upper == 'INCREASE':
                # Suggest adding enough to reach target_pct from current_pct
                portfolio_value = (current_qty * current_price) / (current_pct / 100) if current_pct else 0
                suggested_amount = round((target_pct / 100 - current_pct / 100) * portfolio_value, 2)
                suggested_qty    = max(1, int(suggested_amount // current_price)) if current_price else 0
                para2 = (
                    f"Consider adding {suggested_qty} more "
                    f"share{'s' if suggested_qty != 1 else ''} if your risk budget allows. "
                    f"Suggested additional deployment: ₹{max(suggested_amount, 0):,.0f}."
                )

            elif action_upper == 'REALLOCATE':
                para2 = (
                    f"Reduce or exit this position and redeploy capital into "
                    f"higher-opportunity alternatives identified by the system."
                )

            else:
                para2 = (
                    f"Please review this position manually and consult your risk manager "
                    f"before taking action."
                )

            logger.info(
                'generate_mode1_suggestion: %s %s (conf=%.1f%%, risk=%s)',
                action_upper, ticker, confidence_pct, risk_band,
            )

            return '\n\n'.join([para1, para2])

        except Exception as exc:
            logger.error('generate_mode1_suggestion: unexpected error for %s: %s', ticker, exc)
            return (
                f"Unable to generate suggestion for {ticker} at this time. "
                f"Please review the decision data manually. (Error: {exc})"
            )

    # ── Private helpers ─────────────────────────────────────────────────────

    def _format_sector_list(self, sectors: list[str]) -> str:
        """
        Formats a list of sector names into a grammatical phrase.

        Joins with commas and uses 'and' before the final item.

        Args:
            sectors (list[str]): List of sector name strings.

        Returns:
            str: Human-readable sector phrase.

        Example
        -------
        >>> self._format_sector_list(['IT', 'Pharma', 'Banking'])
        'IT, Pharma, and Banking'
        >>> self._format_sector_list(['IT'])
        'IT'
        """
        if not sectors:
            return 'mixed'
        if len(sectors) == 1:
            return sectors[0]
        if len(sectors) == 2:
            return f'{sectors[0]} and {sectors[1]}'
        return ', '.join(sectors[:-1]) + f', and {sectors[-1]}'

    def _get_risk_summary(self, allocations: list[dict]) -> str:
        """
        Returns a concise risk-band summary phrase for a set of allocations.

        Args:
            allocations (list[dict]): Allocation dicts each containing
                a ``'risk_band'`` key with value ``'LOW'`` or ``'MEDIUM'``.

        Returns:
            str: One of ``'LOW risk'``, ``'MEDIUM risk'``, or
            ``'LOW to MEDIUM risk'``.

        Example
        -------
        >>> self._get_risk_summary([{'risk_band': 'LOW'}, {'risk_band': 'LOW'}])
        'LOW risk'
        """
        if not allocations:
            return 'UNKNOWN risk'
        bands = {a.get('risk_band', '').upper() for a in allocations}
        if bands == {'LOW'}:
            return 'LOW risk'
        if bands == {'MEDIUM'}:
            return 'MEDIUM risk'
        return 'LOW to MEDIUM risk'

    def _compute_reduce_quantity(
        self,
        current_qty: int,
        current_pct: float,
        target_pct: float,
        price: float,
    ) -> int:
        """
        Computes the number of shares to sell to reach the target allocation.

        Calculates the implied portfolio value from ``current_qty``,
        ``current_pct``, and ``price``, then derives the shares to sell
        so the remaining position sits at ``target_pct``.

        Args:
            current_qty (int): Shares currently held.
            current_pct (float): Current position as % of portfolio (0-100).
            target_pct (float): Desired position as % of portfolio (0-100).
            price (float): Current share price in rupees.

        Returns:
            int: Number of shares to sell. Clamped to ``[0, current_qty]``.

        Example
        -------
        >>> self._compute_reduce_quantity(100, 40.0, 20.0, 500.0)
        50
        """
        try:
            if current_pct <= 0 or price <= 0:
                return 0
            # Implied total portfolio value
            portfolio_value = (current_qty * price) / (current_pct / 100)
            target_rupees   = (target_pct / 100) * portfolio_value
            target_shares   = int(target_rupees // price)
            shares_to_sell  = current_qty - target_shares
            # Clamp: can't sell more than held, can't sell negative
            return max(0, min(shares_to_sell, current_qty))
        except Exception as exc:
            logger.error('_compute_reduce_quantity: error: %s', exc)
            return 0

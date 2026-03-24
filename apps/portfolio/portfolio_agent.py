"""
Phase 1 Portfolio Agent for CRPMS.
User-facing intelligence layer that translates numeric agent scores 
and ENUM actions into grammatically correct human-readable suggestions 
using string templates.
"""

from typing import Dict, Any, List, Optional
import logging
import traceback

from apps.portfolio.models import (
    Portfolio, Position, DecisionLog, Watchlist, Alert, SectorMapping
)
from apps.portfolio.state_engine import PortfolioStateEngine
from apps.portfolio.capital_filter import CapitalFilter, OpportunityScorer
from apps.portfolio.capital_allocator import CapitalAllocator
from apps.portfolio.suggestion_generator import SuggestionGenerator
# DRAWDOWN GUARD — Phase 2 addition
from apps.portfolio.drawdown_guard import DrawdownGuard
from django.conf import settings
from utils.helpers import get_ist_now

logger = logging.getLogger('apps.portfolio.portfolio_agent')


class PortfolioAgent:
    """
    Translates agent scores and decision outputs into human-readable suggestions.
    Phase 1: Uses deterministic Python string templates.
    Phase 2: Will be upgraded to use LLM/ML via the ML_RISK_AGENT feature flag.
    """

    def __init__(self):
        self.state_engine = PortfolioStateEngine()

    def generate_portfolio_suggestion(self) -> Dict[str, Any]:
        """
        Main method — generates suggestion for all current positions based on the latest state.

        Returns:
            Dict[str, Any]: Output dictionary containing the portfolio summary, active alerts,
                            and position-specific generated text strings.
            Example:
            {
                'generated_at': '2023-10-27 10:00:00+05:30',
                'portfolio_summary': 'Portfolio is actively monitored.',
                'positions': [{'ticker': 'AAPL', 'action': 'HOLD', ...}],
                'active_alerts': [...],
                'risk_budget_used_pct': 45.2
            }
        """
        try:
            # 1. Get current portfolio state
            state = self.state_engine.get_current_state()
            if not state:
                return {
                    'error': 'State unavailable. Check Redis or DB.',
                    'suggestion_text': 'Data unavailable.'
                }

            portfolio = Portfolio.objects.first()
            if not portfolio:
                return {
                    'error': 'No active portfolio found.',
                    'suggestion_text': 'Data unavailable.'
                }

            # 2. Extract agent outputs and metrics from state
            agent_outputs = state.get('agent_outputs', {})
            risk_budget_used_pct = state.get('risk_metrics', {}).get('risk_budget_used_pct', 0.0)

            # DRAWDOWN GUARD — Phase 2 addition
            # Instantiate once and pass to every position — avoids repeated cache reads
            guard = DrawdownGuard()
            guard_status = guard.check_guard_status()

            # 3. Process each active position
            position_suggestions = []
            active_positions = Position.objects.filter(portfolio=portfolio, quantity__gt=0)
            
            for pos in active_positions:
                ticker = pos.watchlist.ticker
                # Get the latest decision log for this ticker
                decision = DecisionLog.objects.filter(ticker=ticker).order_by('-timestamp').first()
                if decision:
                    suggestion = self._build_position_suggestion(decision, state, guard_status)
                    position_suggestions.append(suggestion)

            # 4. Fetch active/unacknowledged alerts
            active_alerts = list(Alert.objects.filter(is_acknowledged=False).values(
                'ticker__ticker', 'alert_type', 'message', 'created_at'
            ))

            # 5. Assemble overall portfolio summary
            return {
                'generated_at': str(get_ist_now()),
                'portfolio_summary': self._generate_portfolio_summary(active_alerts, risk_budget_used_pct),
                'positions': position_suggestions,
                'active_alerts': active_alerts,
                'risk_budget_used_pct': risk_budget_used_pct,
                # DRAWDOWN GUARD — Phase 2 addition
                'drawdown_guard': guard_status,
                'drawdown_guard_summary': guard.get_guard_summary_text(guard_status),
            }

        except Exception as e:
            logger.error(f"Failed to generate portfolio suggestion: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'error': str(e),
                'suggestion_text': 'Data unavailable.'
            }

    def _generate_portfolio_summary(self, alerts: List[Dict], risk_budget: float) -> str:
        """Helper to generate a high-level summary string for the portfolio."""
        if len(alerts) > 0 and risk_budget > 80.0:
            return f"ATTENTION: Portfolio risk budget is critically high ({risk_budget:.1f}%). Immediate action required on {len(alerts)} alerts."
        elif len(alerts) > 0:
            return f"Portfolio requires attention. You have {len(alerts)} active alerts to review."
        return "Portfolio is stable. All positions are operating within acceptable parameters."

    def _build_position_suggestion(
        self,
        decision: DecisionLog,
        state: Dict[str, Any],
        guard_status: Optional[Dict[str, Any]] = None,  # DRAWDOWN GUARD — Phase 2 addition
    ) -> Dict[str, Any]:
        """
        Builds a human-readable suggestion dictionary for a single position.

        Args:
            decision (DecisionLog): The latest engine decision for the ticker.
            state (Dict[str, Any]): The unified portfolio state dict.
            guard_status (dict | None): Pre-computed guard status from
                :class:`DrawdownGuard`. When provided, INCREASE and REALLOCATE
                actions are overridden to HOLD during capital preservation mode.

        Returns:
            Dict[str, Any]: A structured suggestion payload for the position.
        """
        try:
            ticker = decision.ticker.ticker
            agent_outputs = state.get('agent_outputs', {})
            ticker_agents = agent_outputs.get(ticker, {})

            # Extract metrics from agent outputs for the template mapping
            market_risk = ticker_agents.get('market_risk') or {}
            sentiment = ticker_agents.get('sentiment') or {}
            fundamental = ticker_agents.get('fundamental') or {}
            
            risk_band = market_risk.get('band', 'UNKNOWN')
            sentiment_score = sentiment.get('score')
            fundamental_score = fundamental.get('score')

            # DRAWDOWN GUARD — Phase 2 addition
            # Apply guard override before generating suggestion text
            action = decision.action
            guard_override = False
            guard_override_reason = ''
            if guard_status:
                guard_instance = DrawdownGuard()
                action, guard_override_reason = guard_instance.apply_guard(
                    decision.action, ticker, guard_status
                )
                guard_override = bool(guard_override_reason)

            # Generate the natural language text using the (possibly overridden) action
            suggestion_text = self._generate_suggestion_text(ticker, action, decision, ticker_agents)

            result = {
                'ticker': ticker,
                'action': action,
                'confidence_pct': float(decision.confidence_score) if decision.confidence_score else 0.0,
                'suggestion_text': suggestion_text,
                'risk_band': risk_band,
                'sentiment_score': float(sentiment_score) if sentiment_score is None else sentiment_score,
                'fundamental_score': float(fundamental_score) if fundamental_score is None else fundamental_score,
            }
            # DRAWDOWN GUARD — Phase 2 addition
            if guard_override:
                result['guard_override'] = True
                result['guard_override_reason'] = guard_override_reason
            return result

        except Exception as e:
            logger.error(f"Failed to build suggestion for {decision.ticker.ticker}: {str(e)}")
            return {
                'ticker': decision.ticker.ticker,
                'action': decision.action,
                'confidence_pct': 0.0,
                'suggestion_text': 'Data unavailable.',
                'risk_band': 'UNKNOWN',
                'sentiment_score': None,
                'fundamental_score': None,
            }

    def _generate_suggestion_text(self, ticker: str, action: str, decision: DecisionLog, agent_outputs: Dict[str, Any]) -> str:
        """
        Template-based natural language text generator.
        Replaces placeholders in pre-defined constraint strings depending on the action enum.

        Args:
            ticker (str): The stock ticker.
            action (str): The decision action (HOLD, REDUCE, etc.).
            decision (DecisionLog): The DB object containing the decision metadata.
            agent_outputs (Dict[str, Any]): The agent outputs data mapping for this ticker.

        Returns:
            str: Grammatically correct human-readable sentence.
        """
        try:
            # Safely extract formatting variables with defaults
            market_risk = agent_outputs.get('market_risk') or {}
            sentiment = agent_outputs.get('sentiment') or {}
            fundamental = agent_outputs.get('fundamental') or {}
            opportunity = agent_outputs.get('opportunity') or {}

            risk_score = float(market_risk.get('score', 0))
            risk_band = market_risk.get('band', 'UNKNOWN')
            flags = market_risk.get('risk_flags', {})
            
            sentiment_score = float(sentiment.get('score', 0))
            sentiment_label = self._get_sentiment_label(sentiment_score)
            
            fundamental_score = float(fundamental.get('score', 0))
            current_opp_score = float(opportunity.get('score', 0))

            qty_value = decision.metadata.get('suggested_quantity', 'your') if isinstance(decision.metadata, dict) else 'your'

            if action == 'HOLD':
                return (
                    f"{ticker} is currently stable. Risk level is {risk_band} with a score of "
                    f"{risk_score:.0f}/100. Sentiment over the last 24 hours is {sentiment_label}. "
                    "No action required at this time. Continue monitoring."
                )
            
            elif action == 'REDUCE':
                risk_reason = self._get_risk_reason(risk_score, flags)
                return (
                    f"{ticker} is showing elevated risk (score: {risk_score:.0f}/100, band: {risk_band}). "
                    f"{risk_reason}. Recommend reducing position size by 30-50% to manage exposure. "
                    f"Sentiment is {sentiment_label}. Consider selling {qty_value} shares."
                )

            elif action == 'EXIT':
                exit_reason = self._get_risk_reason(risk_score, flags)
                return (
                    f"URGENT: {ticker} has triggered an exit signal. {exit_reason}. "
                    f"Risk score: {risk_score:.0f}/100. Recommend exiting full position of {qty_value} shares "
                    "immediately to prevent further losses."
                )

            elif action == 'INCREASE':
                return (
                    f"{ticker} presents a strong buying opportunity. Risk is LOW (score: {risk_score:.0f}/100), "
                    f"fundamentals are solid (score: {fundamental_score:.0f}/100), and sentiment is "
                    f"{sentiment_label}. Consider increasing position if budget allows."
                )

            elif action == 'REALLOCATE':
                return (
                    f"Consider reallocating capital from {ticker} to a higher-opportunity position. "
                    f"{ticker} opportunity score ({current_opp_score:.0f}) is significantly below available "
                    "alternatives. Free up capital by reducing or exiting this position."
                )
            
            return "Recommendation is pending further data collection."

        except Exception as e:
            logger.error(f"Template generation failed for {ticker}: {str(e)}")
            return "Data unavailable."

    def _get_risk_reason(self, risk_score: float, flags: Dict[str, Any]) -> str:
        """
        Translates raw risk flags or scores into human-readable sentences.

        Args:
            risk_score (float): The market risk score out of 100.
            flags (Dict[str, Any]): Warning flags emitted by the risk agent.

        Returns:
            str: Explanatory phrase.
        """
        if flags.get('stop_loss_breached', False):
            return "Stop-loss threshold breached"
        elif flags.get('volatility_spike', False):
            return "Volatility has increased sharply over the past 5 days"
        elif flags.get('event_risk_detected', False):
            return "Event risk detected: regulatory keyword in recent news"
        
        # Fallbacks if no specific dictionary flags are set
        if risk_score > 85:
            return "Extreme market downside probabilities flagged by predictive models"
        elif risk_score > 70:
            return "Recent price actions indicate technical breakdowns"
            
        return "Internal risk limits approach threshold limits"

    def _get_sentiment_label(self, sentiment_score: float) -> str:
        """
        Translates a -1.0 to 1.0 compound score into categorical text.

        Args:
            sentiment_score (float): The raw compound score from the NLP engine.

        Returns:
            str: positive, negative, or neutral.
        """
        if sentiment_score > 0.2:
            return "positive"
        elif sentiment_score < -0.2:
            return "negative"
        return "neutral"

    def generate_capital_deployment_suggestion(
        self,
        available_capital: float,
        preferred_sectors: List[str],
        max_positions: int = 5,
        min_opportunity_score: float = 40.0,
    ) -> Dict[str, Any]:
        """
        Mode 2 — Full fresh capital deployment logic.

        Runs the complete pipeline: sector → ticker lookup, risk filter,
        price filter, opportunity scoring, capital allocation, and natural
        language suggestion generation. All steps are wrapped in a single
        try/except so any unexpected failure returns a structured error dict.

        Args:
            available_capital (float): Rupees available to deploy (must be > 0).
            preferred_sectors (list[str]): Sector names from SectorMapping
                (e.g. ``['IT', 'Pharma']``).
            max_positions (int): Maximum number of stocks to select (default 5).
            min_opportunity_score (float): Minimum opportunity score to qualify
                a candidate (default 40.0).

        Returns:
            Dict[str, Any]: Full suggestion dict with keys ``mode``, ``status``,
            ``generated_at``, ``input``, ``allocation``, ``suggestion_text``,
            and ``warnings``. Returns a dict with ``status='error'`` on failure.

        Example
        -------
        >>> agent = PortfolioAgent()
        >>> result = agent.generate_capital_deployment_suggestion(500_000, ['IT', 'Pharma'])
        >>> result['status']
        'success'
        """
        import time
        start_time = time.time()

        try:
            # ── Input validation ──────────────────────────────────────────
            if available_capital <= 0:
                return {
                    'mode': 'fresh_capital_deployment',
                    'status': 'error',
                    'suggestion_text': (
                        'Available capital must be greater than zero. '
                        'Please enter a positive rupee amount.'
                    ),
                    'allocation': {'allocations': [], 'summary': {}},
                    'warnings': ['available_capital must be > 0'],
                }

            if not preferred_sectors:
                return {
                    'mode': 'fresh_capital_deployment',
                    'status': 'error',
                    'suggestion_text': (
                        'No sectors specified. Please select at least one sector '
                        'from your watchlist to receive investment suggestions.'
                    ),
                    'allocation': {'allocations': [], 'summary': {}},
                    'warnings': ['preferred_sectors is empty'],
                }

            if available_capital < 10_000:
                return {
                    'mode': 'fresh_capital_deployment',
                    'status': 'warning',
                    'suggestion_text': (
                        f'₹{available_capital:,.0f} is below the recommended minimum of ₹10,000. '
                        f'At this capital level it may not be possible to build a diversified '
                        f'position across multiple stocks. Consider increasing your deployment amount.'
                    ),
                    'allocation': {'allocations': [], 'summary': {}},
                    'warnings': ['Capital below ₹10,000 minimum recommended threshold'],
                }

            # DRAWDOWN GUARD — Phase 2 addition
            # Block fresh capital deployment entirely while guard is active
            guard = DrawdownGuard()
            guard_status = guard.check_guard_status()
            if guard_status['active']:
                return {
                    'mode': 'fresh_capital_deployment',
                    'status': 'guard_active',
                    'suggestion_text': (
                        'Fresh capital deployment is currently suspended. '
                        f'{guard.get_guard_summary_text(guard_status)} '
                        'Wait for the portfolio to recover before deploying new capital.'
                    ),
                    'guard_status': guard_status,
                    'allocation': {'allocations': [], 'summary': {}},
                    'warnings': [guard_status['message']],
                }

            # ── Step 1 — Sector → ticker mapping ─────────────────────────
            tickers = list(
                SectorMapping.objects
                .filter(sector__in=preferred_sectors)
                .values_list('ticker__ticker', flat=True)
                .distinct()
            )
            logger.info(
                'Mode 2: Found %d tickers in sectors %s', len(tickers), preferred_sectors
            )
            if not tickers:
                return {
                    'mode': 'fresh_capital_deployment',
                    'status': 'error',
                    'suggestion_text': (
                        f'No tickers found for the specified sectors: '
                        f'{", ".join(preferred_sectors)}. '
                        f'Please run the load_sector_data management command first.'
                    ),
                    'allocation': {'allocations': [], 'summary': {}},
                    'warnings': ['No tickers found for specified sectors'],
                }

            # ── Step 2 — Risk filtering ───────────────────────────────────
            capital_filter = CapitalFilter()
            risk_candidates = capital_filter.filter_by_risk(tickers)
            risk_candidates = capital_filter.filter_by_price_availability(risk_candidates)

            if not risk_candidates:
                return self._no_candidates_dict(
                    'All stocks in the selected sectors are currently rated HIGH or CRITICAL risk'
                )

            # ── Step 3 — Opportunity scoring and selection ────────────────
            scorer = OpportunityScorer()
            scored_candidates = scorer.score_candidates(risk_candidates)
            selected = scorer.rank_and_select(
                scored_candidates, max_positions, min_opportunity_score
            )

            if not selected:
                return self._no_candidates_dict(
                    f'No candidates met the minimum opportunity score threshold ({min_opportunity_score})'
                )

            # ── Step 4 — Capital allocation ───────────────────────────────
            allocator = CapitalAllocator()
            allocation_result = allocator.allocate(selected, available_capital)
            warnings = allocator.validate_allocation(allocation_result)

            # ── Step 5 — Suggestion text ──────────────────────────────────
            generator = SuggestionGenerator()
            suggestion_text = generator.generate_mode2_suggestion(
                available_capital, preferred_sectors, allocation_result, warnings
            )

            # ── Step 6 — Return full result ───────────────────────────────
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            logger.info(
                'Mode 2 completed in %sms — %d positions, ₹%.0f deployed',
                elapsed_ms,
                allocation_result.get('summary', {}).get('num_positions', 0),
                allocation_result.get('summary', {}).get('total_deployed', 0),
            )

            return {
                'mode': 'fresh_capital_deployment',
                'status': 'success',
                'generated_at': get_ist_now().isoformat(),
                'input': {
                    'available_capital': available_capital,
                    'preferred_sectors': preferred_sectors,
                    'tickers_evaluated': len(tickers),
                    'tickers_qualified': len(selected),
                },
                'allocation': allocation_result,
                'suggestion_text': suggestion_text,
                'warnings': warnings,
            }

        except Exception as exc:
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            logger.error(
                'Mode 2 failed after %sms: %s', elapsed_ms, exc, exc_info=True
            )
            return {
                'mode': 'fresh_capital_deployment',
                'status': 'error',
                'suggestion_text': (
                    'An unexpected error occurred while generating the capital deployment plan. '
                    f'Please try again or contact support. (Error: {exc})'
                ),
                'allocation': {'allocations': [], 'summary': {}},
                'warnings': [str(exc)],
            }

    def _no_candidates_dict(self, reason: str) -> Dict[str, Any]:
        """
        Returns a structured user-friendly dict when no candidates qualify.

        Used internally by :meth:`generate_capital_deployment_suggestion` when
        risk filtering or opportunity scoring eliminates all tickers.

        Args:
            reason (str): Short description of why no candidates qualified.

        Returns:
            Dict[str, Any]: Standard response dict with ``status='no_candidates'``.
        """
        return {
            'mode': 'fresh_capital_deployment',
            'status': 'no_candidates',
            'generated_at': get_ist_now().isoformat(),
            'suggestion_text': (
                f'No suitable investment opportunities found: {reason}. '
                f'All stocks in your preferred sectors are currently rated '
                f'HIGH or CRITICAL risk. Consider waiting for better market '
                f'conditions or expanding your sector preferences.'
            ),
            'allocation': {'allocations': [], 'summary': {}},
            'warnings': [reason],
        }

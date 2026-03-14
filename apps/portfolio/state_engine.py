"""
Portfolio State Engine for CRPMS.
Aggregates position data, market data, and agent outputs into a 
unified portfolio state snapshot suitable for the dashboard and decision engine.
"""

from typing import Dict, List, Any, Optional
import logging
from decimal import Decimal
import traceback

from apps.portfolio.models import (
    Portfolio, Position, AgentOutput, PortfolioStateSnapshot, Watchlist, PriceHistory
)
# DRAWDOWN GUARD — Phase 2 addition
from apps.portfolio.drawdown_guard import DrawdownGuard
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone

from utils.cache import get_all_agent_outputs_for_ticker, set_portfolio_state
from utils.helpers import get_ist_now, safe_divide

logger = logging.getLogger('apps.portfolio.state_engine')


class PortfolioStateEngine:
    """
    Central state manager for the Portfolio app. 
    It reads agent outputs and position data, and produces a unified 
    portfolio state snapshot written to both Redis and PostgreSQL.
    """

    def __init__(self):
        pass

    def update_state(self) -> Dict[str, Any]:
        """
        Main entry point. Orchestrates full state update cycle including price updates,
        metric aggregation, agent aggregation, and writing the final snapshot.

        Returns:
            Dict[str, Any]: The fully compiled state dictionary. 
                            Returns an empty dict if a failure occurs.
        """
        try:
            # 1. Get the active Portfolio object (assumes a single portfolio architecture for now)
            portfolio = Portfolio.objects.first()
            if not portfolio:
                logger.warning("update_state aborting: No Portfolio found.")
                return {}

            # 2. Get all active positions from DB
            positions = list(Position.objects.filter(portfolio=portfolio, quantity__gt=0).select_related('watchlist'))

            # 3. For each position: call _update_position_price
            for pos in positions:
                self._update_position_price(pos)

            # 4. Call _compute_portfolio_metrics
            metrics = self._compute_portfolio_metrics(portfolio, positions)

            # 5. Call _aggregate_agent_outputs
            agent_data, stale_agents = self._aggregate_agent_outputs(positions)

            # 6. Assemble state_dict
            state_dict = {
                'timestamp': str(get_ist_now()),
                'portfolio_metrics': metrics,
                'agent_outputs': agent_data,
                'stale_agents': list(set(stale_agents + self.detect_stale_data())),
                'risk_metrics': {
                    'risk_budget_used_pct': self._compute_risk_budget_used(agent_data),
                }
            }

            # DRAWDOWN GUARD — Phase 2 addition
            # Check guard state before snapshot write so guard data is persisted in history
            try:
                guard = DrawdownGuard()
                # Read previous state to detect transition (inactive → active)
                prev_guard_state = cache.get('portfolio:drawdown_guard_state') or {}
                was_active = prev_guard_state.get('active', False)

                guard_status = guard.check_guard_status()

                # Fire alert only on the activation transition
                if guard_status['active'] and not was_active:
                    guard.create_guard_alert(guard_status)
                    logger.warning('update_state: DrawdownGuard transitioned to ACTIVE — alert created')

                # Embed guard data into state so dashboard and agents can read it
                state_dict['drawdown_guard'] = guard_status
                state_dict['drawdown_guard_summary'] = guard.get_guard_summary_text(guard_status)
            except Exception as guard_exc:
                logger.error('update_state: DrawdownGuard check failed: %s', guard_exc)
                state_dict['drawdown_guard'] = {'active': False}
                state_dict['drawdown_guard_summary'] = '⚠️ Drawdown Guard status unavailable.'

            # 7. Call _write_snapshot
            self._write_snapshot(portfolio, state_dict)
            
            logger.info(f"Portfolio state updated successfully. Value: {metrics.get('total_value', 0.0)}")

            # 8. Return state_dict
            return state_dict

        except Exception as e:
            logger.error(f"Failed to execute update_state: {str(e)}")
            logger.error(traceback.format_exc())
            return {}

    def _update_position_price(self, position: Position) -> None:
        """
        Reads the latest PriceHistory record for a position to update its current price
        and unrealised PnL.

        Args:
            position (Position): The position object to update.
        """
        try:
            latest_price_obj = PriceHistory.objects.filter(
                ticker=position.watchlist
            ).order_by('-date').first()

            if latest_price_obj and latest_price_obj.close_price:
                position.current_price = latest_price_obj.close_price
                
                # Recalculate PnL ((current - avg_buy) * quantity)
                if position.avg_buy_price is not None:
                    position.unrealised_pnl = (position.current_price - position.avg_buy_price) * position.quantity
                
                # Save only the changed fields for database efficiency
                position.save(update_fields=['current_price', 'unrealised_pnl', 'updated_at'])

        except Exception as e:
            logger.error(f"Failed to update position price for {position.watchlist.ticker}: {str(e)}")

    def _compute_portfolio_metrics(self, portfolio: Portfolio, positions: List[Position]) -> Dict[str, Any]:
        """
        Aggregates financial metrics for the portfolio based on its constituent positions.

        Args:
            portfolio (Portfolio): The parent portfolio object.
            positions (List[Position]): A list of all active position objects for the portfolio.

        Returns:
            Dict[str, Any]: A dictionary containing calculated totals (value, cost, pnl) 
                            and structural exposures mapping.
        """
        try:
            total_value = sum(
                float(pos.current_price or 0.0) * float(pos.quantity) 
                for pos in positions
            )
            total_cost_basis = sum(float(pos.cost_basis) for pos in positions)
            total_unrealised_pnl = sum(float(pos.unrealised_pnl or 0.0) for pos in positions)
            
            # (total_value - total_cost) / total_cost * 100
            total_pnl_pct = safe_divide((total_value - total_cost_basis), total_cost_basis) * 100.0

            # Compute allocation mapping and re-calculate the percentage inline
            # to guarantee the aggregate total matches the map.
            allocation_pct_map = {}
            for pos in positions:
                pos_value = float(pos.current_price or 0.0) * float(pos.quantity)
                pct = safe_divide(pos_value, total_value) * 100.0
                allocation_pct_map[pos.watchlist.ticker] = pct
                
                # Update the DB field if we calculated it, for consistency
                pos.allocation_pct = Decimal(str(pct))
                pos.save(update_fields=['allocation_pct', 'updated_at'])

            sector_exposure, _ = self._compute_sector_exposure(positions)

            return {
                'total_value': float(total_value),
                'total_cost_basis': float(total_cost_basis),
                'total_unrealised_pnl': float(total_unrealised_pnl),
                'total_pnl_pct': float(total_pnl_pct),
                'available_capital': float(portfolio.available_capital),
                'deployed_capital': float(total_cost_basis),
                'allocation_pct_map': allocation_pct_map,
                'sector_exposure': sector_exposure,
                'position_count': len(positions)
            }
        except Exception as e:
            logger.error(f"Failed to compute portfolio metrics: {str(e)}")
            return {}

    def _aggregate_agent_outputs(self, positions: List[Position]) -> tuple[Dict[str, Any], List[str]]:
        """
        Fetches all agent outputs for the tickers currently held in the portfolio.

        Args:
            positions (List[Position]): The active portfolio positions.

        Returns:
            tuple[Dict[str, Any], List[str]]: A tuple containing:
                - A mapping of ticker to its respective agent outputs.
                - A list of agent names globally flagged as stale.
        """
        agent_data = {}
        stale_agents = set()

        try:
            for pos in positions:
                ticker = pos.watchlist.ticker
                outputs = get_all_agent_outputs_for_ticker(ticker)
                agent_data[ticker] = outputs

                # Check if any agent missed the cache delivery or returned empty
                # We do not do strict timestamp checking here, rely on detect_stale_data() for that
                for agent_name, payload in outputs.items():
                    if payload is None:
                        stale_agents.add(agent_name)

            return agent_data, list(stale_agents)

        except Exception as e:
            logger.error(f"Failed to aggregate agent outputs: {str(e)}")
            return {}, list(stale_agents)

    def _compute_risk_budget_used(self, agent_outputs: Dict[str, Any]) -> float:
        """
        Calculates what percentage of the system's maximum allowable portfolio VaR 
        is currently being consumed based on market_risk agent outputs.

        Args:
            agent_outputs (Dict[str, Any]): The nested agent dataset by ticker.

        Returns:
            float: Percentage value between 0.0 and 100.0. Returns 0.0 on error.
        """
        try:
            max_var = float(getattr(settings, 'CRPMS', {}).get('MAX_PORTFOLIO_VAR', 0.02))
            if max_var <= 0:
                return 0.0

            total_system_var = 0.0
            
            # Sum up VaR contributions from all active positions
            for ticker, agents in agent_outputs.items():
                market_risk = agents.get('market_risk')
                if market_risk and isinstance(market_risk, dict):
                    # We assume the agent outputs a 'var_contribution' or 'var' field directly
                    var_val = market_risk.get('var_contribution', market_risk.get('var', 0.0))
                    total_system_var += float(var_val)

            # risk used = total current VaR / max allowed VaR
            utilization_pct = safe_divide(total_system_var, max_var) * 100.0
            return float(min(100.0, utilization_pct)) # Cap at 100%
            
        except Exception as e:
            logger.error(f"Failed to compute risk budget used: {str(e)}")
            return 0.0

    def _compute_sector_exposure(self, positions: List[Position]) -> tuple[Dict[str, float], List[str]]:
        """
        Aggregates allocation percentages grouped by sector and flags concentrated sectors.

        Args:
            positions (List[Position]): The active portfolio positions.

        Returns:
            tuple[Dict[str, float], List[str]]: A tuple containing:
                - Mapping of sector name to total sum of allocation percentage.
                - List of sector names exceeding the concentration limit constraint.
        """
        exposure = {}
        flagged_sectors = []
        try:
            limit = float(getattr(settings, 'CRPMS', {}).get('SECTOR_CONCENTRATION_LIMIT', 0.40)) * 100.0
            
            for pos in positions:
                sector = pos.watchlist.sector or 'Unknown'
                exposure[sector] = exposure.get(sector, 0.0) + float(pos.allocation_pct or 0.0)

            for sector, total_alloc in exposure.items():
                if total_alloc > limit:
                    flagged_sectors.append(sector)

            return exposure, flagged_sectors
        except Exception as e:
            logger.error(f"Failed to compute sector exposure: {str(e)}")
            return {}, []

    def detect_stale_data(self) -> List[str]:
        """
        Checks the PostgreSQL Database to determine if any underlying agent
        infrastructure has failed to produce an output within the last 1 hour.

        Returns:
            List[str]: A list of agent names (enums) that are currently stale.
        """
        stale_agents = []
        try:
            one_hour_ago = get_ist_now() - timezone.timedelta(hours=1)
            
            # Check all 4 agents
            for agent_choice in AgentOutput.AgentName.values:
                # Find the very last output produced by this agent type across any ticker
                latest_output = AgentOutput.objects.filter(
                    agent_name=agent_choice
                ).order_by('-timestamp').first()
                
                # If there are NO outputs ever, or the latest is > 1 hour old, flag it
                if not latest_output or latest_output.timestamp < one_hour_ago:
                    stale_agents.append(agent_choice)
                    
            return stale_agents
        except Exception as e:
            logger.error(f"Failed to detect stale data from DB: {str(e)}")
            return []

    def get_current_state(self) -> Dict[str, Any]:
        """
        Retrieves the latest generated portfolio state from Redis natively. 
        If the cache expires, it forcefully triggers an immediate update_state() calculation.

        Returns:
            Dict[str, Any]: The unified state dictionary payload.
        """
        try:
            key = "portfolio:current_state"
            state = cache.get(key)
            if state:
                return state
                
            logger.info("Portfolio state missing from cache. Generating cold state...")
            return self.update_state()
            
        except Exception as e:
            logger.error(f"Failed to retrieve current state: {str(e)}")
            return {}

    def _write_snapshot(self, portfolio: Portfolio, state_dict: Dict[str, Any]) -> None:
        """
        Commits the newly generated state dictionary to Redis for rapid access,
        and to PostgreSQL for historical chronological playback.

        Args:
            portfolio (Portfolio): The parent portfolio object.
            state_dict (Dict[str, Any]): The full state bundle containing metrics and outputs.
        """
        try:
            # Redis Write - Hardcoded 15m TTL in cache utility
            set_portfolio_state(state_dict)

            # PostgreSQL Write
            PortfolioStateSnapshot.objects.create(
                portfolio=portfolio,
                state_data=state_dict,  # Django JSONField natively serialises dicts
                timestamp=get_ist_now()
            )
        except Exception as e:
            logger.error(f"Failed to write snapshot to stores: {str(e)}")

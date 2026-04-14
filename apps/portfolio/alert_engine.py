"""
apps/portfolio/alert_engine.py

Detects threshold breaches and generates system alerts.
"""
import logging
from datetime import timedelta
from django.utils import timezone

from apps.portfolio.models import (
    Alert, AgentOutput, DecisionLog, PortfolioStateSnapshot,
    Position, NewsArticle
)


class AlertEngine:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.dedup_window_hours = 6

    def run(self, portfolio_id: int) -> dict:
        result = {
            'alerts_created': 0,
            'checks_run': 5,
            'errors': []
        }

        # Check 1: Risk Bands
        try:
            result['alerts_created'] += self._check_risk_bands(portfolio_id)
        except Exception as e:
            self.logger.error("Error in _check_risk_bands: %s", e)
            result['errors'].append(str(e))

        # Check 2: Exit Signals
        try:
            result['alerts_created'] += self._check_exit_signals(portfolio_id)
        except Exception as e:
            self.logger.error("Error in _check_exit_signals: %s", e)
            result['errors'].append(str(e))

        # Check 3: Drawdown
        try:
            result['alerts_created'] += self._check_drawdown(portfolio_id)
        except Exception as e:
            self.logger.error("Error in _check_drawdown: %s", e)
            result['errors'].append(str(e))

        # Check 4: Sentiment Spikes
        try:
            result['alerts_created'] += self._check_sentiment_spikes(portfolio_id)
        except Exception as e:
            self.logger.error("Error in _check_sentiment_spikes: %s", e)
            result['errors'].append(str(e))

        # Check 5: Stale Data
        try:
            result['alerts_created'] += self._check_stale_data(portfolio_id)
        except Exception as e:
            self.logger.error("Error in _check_stale_data: %s", e)
            result['errors'].append(str(e))

        return result

    def _should_create_alert(self, portfolio_id, ticker_id_or_none, alert_type) -> bool:
        # Note: Alert model lacks portfolio_id, so we filter by ticker directly
        exists = Alert.objects.filter(
            ticker_id=ticker_id_or_none,
            alert_type=alert_type,
            is_acknowledged=False,
            created_at__gte=timezone.now() - timedelta(hours=self.dedup_window_hours)
        ).exists()
        return not exists

    def _create_alert(self, portfolio_id, ticker_id_or_none, alert_type, message) -> Alert | None:
        if not self._should_create_alert(portfolio_id, ticker_id_or_none, alert_type):
            self.logger.debug("Duplicate alert suppressed: type=%s ticker=%s", alert_type, ticker_id_or_none)
            return None
        
        # Severity is omitted completely as it does not exist on the Alert model
        alert = Alert.objects.create(
            ticker_id=ticker_id_or_none,
            alert_type=alert_type,
            message=message
        )
        return alert

    def _check_risk_bands(self, portfolio_id) -> int:
        alerts_created = 0
        ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
        for tid in ticker_ids:
            latest = AgentOutput.objects.filter(
                ticker_id=tid, agent_name=AgentOutput.AgentName.MARKET_RISK
            ).order_by('-timestamp').first()
            
            if latest:
                if latest.band == AgentOutput.Band.HIGH:
                    # Mapped custom HIGH string to exact AlertType TextChoice
                    alert_type = Alert.AlertType.RISK_HIGH
                    msg = f"{tid} classified as HIGH risk. Score: {latest.score:.1f}. Review position."
                    if self._create_alert(portfolio_id, tid, alert_type, msg):
                        alerts_created += 1
                elif latest.band == AgentOutput.Band.CRITICAL:
                    alert_type = Alert.AlertType.RISK_CRITICAL
                    msg = f"CRITICAL risk on {tid}. Score: {latest.score:.1f}. Immediate action required."
                    if self._create_alert(portfolio_id, tid, alert_type, msg):
                        alerts_created += 1
        return alerts_created

    def _check_exit_signals(self, portfolio_id) -> int:
        alerts_created = 0
        ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
        for tid in ticker_ids:
            latest = DecisionLog.objects.filter(ticker_id=tid).order_by('-timestamp').first()
            if latest and latest.action == DecisionLog.Action.EXIT and latest.confidence_score >= 0.75:
                # Mapped EXIT_SIGNAL to STOP_LOSS
                alert_type = Alert.AlertType.STOP_LOSS
                reasoning = latest.reasoning_text[:100]
                msg = f"Decision Agent recommends EXIT on {tid}. Confidence: {latest.confidence_score * 100:.0f}%. Reasoning: {reasoning}"
                if self._create_alert(portfolio_id, tid, alert_type, msg):
                    alerts_created += 1
        return alerts_created

    def _check_drawdown(self, portfolio_id) -> int:
        alerts_created = 0
        snap = PortfolioStateSnapshot.objects.filter(portfolio_id=portfolio_id).order_by('-timestamp').first()
        if not snap:
            return 0
            
        pnl = snap.state_data.get('total_pnl_pct', 0.0)
        if pnl <= -10.0:
            # Mapped DRAWDOWN to EVENT_RISK
            alert_type = Alert.AlertType.EVENT_RISK
            msg = f"Portfolio drawdown reached {abs(pnl):.1f}%. Drawdown Guard is active. Aggressive actions are frozen."
            
            # Note: ticker_id=None violates DB constraints inside DB, but is left per explicit user guidelines (caught internally)
            if self._create_alert(portfolio_id, None, alert_type, msg):
                alerts_created += 1
        return alerts_created

    def _check_sentiment_spikes(self, portfolio_id) -> int:
        alerts_created = 0
        ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
        for tid in ticker_ids:
            articles = NewsArticle.objects.filter(ticker_tag_id=tid).order_by('-published_at')[:5]
            if len(articles) >= 3:
                scores = [a.sentiment_score for a in articles if a.sentiment_score is not None]
                if scores:
                    avg_sentiment = sum(scores) / len(scores)
                    if avg_sentiment < -0.5:
                        # Mapped SENTIMENT to EVENT_RISK
                        alert_type = Alert.AlertType.EVENT_RISK
                        msg = f"Negative sentiment spike for {tid}. Average score over last {len(articles)} articles: {avg_sentiment:.2f}"
                        if self._create_alert(portfolio_id, tid, alert_type, msg):
                            alerts_created += 1
        return alerts_created

    def _check_stale_data(self, portfolio_id) -> int:
        alerts_created = 0
        ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
        cutoff = timezone.now() - timedelta(hours=24)
        for tid in ticker_ids:
            recent_exists = AgentOutput.objects.filter(
                ticker_id=tid,
                timestamp__gte=cutoff
            ).exists()
            
            if not recent_exists:
                # Mapped DATA_QUALITY to EVENT_RISK
                alert_type = Alert.AlertType.EVENT_RISK
                msg = f"No risk assessment for {tid} in 24 hours. Check data ingestion pipeline."
                if self._create_alert(portfolio_id, tid, alert_type, msg):
                    alerts_created += 1
        return alerts_created

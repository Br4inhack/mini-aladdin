from rest_framework import serializers

from apps.portfolio.models import (
    Watchlist, Portfolio, Position, AgentOutput,
    DecisionLog, Alert, PriceHistory, NewsArticle,
    BacktestResult, PortfolioStateSnapshot
)

class WatchlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Watchlist
        fields = ['id', 'ticker', 'company_name', 'sector', 'exchange', 'is_active']


class PortfolioSummarySerializer(serializers.ModelSerializer):
    position_count = serializers.SerializerMethodField()
    total_pnl_pct = serializers.SerializerMethodField()
    drawdown_guard_active = serializers.SerializerMethodField()

    class Meta:
        model = Portfolio
        fields = [
            'id', 'name', 'total_capital', 'available_capital',
            'created_at', 'position_count', 'total_pnl_pct',
            'drawdown_guard_active'
        ]

    def get_position_count(self, obj):
        try:
            return obj.positions.count()
        except Exception:
            return 0

    def get_total_pnl_pct(self, obj):
        try:
            snap = obj.state_snapshots.order_by('-timestamp').first()
            if snap and isinstance(snap.state_data, dict):
                return float(snap.state_data.get('total_pnl_pct', 0.0))
        except Exception:
            pass
        return 0.0

    def get_drawdown_guard_active(self, obj):
        try:
            snap = obj.state_snapshots.order_by('-timestamp').first()
            if snap and isinstance(snap.state_data, dict):
                return bool(snap.state_data.get('drawdown_guard_active', False))
        except Exception:
            pass
        return False


class PositionSerializer(serializers.ModelSerializer):
    ticker = WatchlistSerializer(source='watchlist', read_only=True)
    risk_band = serializers.SerializerMethodField()
    risk_score = serializers.SerializerMethodField()
    action = serializers.SerializerMethodField()
    action_confidence = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            'id', 'ticker', 'quantity', 'avg_buy_price', 'current_price',
            'unrealised_pnl', 'allocation_pct', 'risk_band', 'risk_score',
            'action', 'action_confidence'
        ]

    def get_risk_band(self, obj):
        try:
            agent = obj.watchlist.agent_outputs.filter(agent_name='market_risk').order_by('-timestamp').first()
            return agent.band if agent and agent.band else 'UNKNOWN'
        except Exception:
            return 'UNKNOWN'

    def get_risk_score(self, obj):
        try:
            agent = obj.watchlist.agent_outputs.filter(agent_name='market_risk').order_by('-timestamp').first()
            return float(agent.score) if agent else None
        except Exception:
            return None

    def get_action(self, obj):
        try:
            log = obj.watchlist.decision_logs.order_by('-timestamp').first()
            return log.action if log else 'HOLD'
        except Exception:
            return 'HOLD'

    def get_action_confidence(self, obj):
        try:
            log = obj.watchlist.decision_logs.order_by('-timestamp').first()
            return float(log.confidence_score) if log else None
        except Exception:
            return None


class AgentOutputSerializer(serializers.ModelSerializer):
    ticker = WatchlistSerializer(read_only=True)

    class Meta:
        model = AgentOutput
        fields = ['id', 'agent_name', 'ticker', 'score', 'band', 'raw_data', 'timestamp']


class DecisionLogSerializer(serializers.ModelSerializer):
    ticker = WatchlistSerializer(read_only=True)

    class Meta:
        model = DecisionLog
        fields = ['id', 'ticker', 'action', 'confidence_score', 'reasoning_text', 'timestamp']


class AlertSerializer(serializers.ModelSerializer):
    ticker = WatchlistSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Alert
        fields = ['id', 'ticker', 'alert_type', 'message', 'is_acknowledged', 'created_at']


class PriceHistorySerializer(serializers.ModelSerializer):
    open = serializers.FloatField()
    high = serializers.FloatField()
    low = serializers.FloatField()
    close = serializers.FloatField()

    class Meta:
        model = PriceHistory
        fields = ['date', 'open', 'high', 'low', 'close', 'volume']


class NewsArticleSerializer(serializers.ModelSerializer):
    ticker = WatchlistSerializer(source='ticker_tag', read_only=True)
    sentiment_label = serializers.SerializerMethodField()
    sentiment_strength = serializers.SerializerMethodField()
    sentiment_color = serializers.SerializerMethodField()

    class Meta:
        model = NewsArticle
        fields = [
            'id', 'ticker', 'headline', 'source', 'published_at',
            'sentiment_score', 'sentiment_label', 'sentiment_strength', 'sentiment_color'
        ]

    def get_sentiment_label(self, obj):
        score = obj.sentiment_score
        if score is None:
            return 'UNKNOWN'
        if score > 0.1:
            return 'POSITIVE'
        if score < -0.1:
            return 'NEGATIVE'
        return 'NEUTRAL'

    def get_sentiment_strength(self, obj):
        score = obj.sentiment_score
        if score is None:
            return None
        abs_score = abs(score)
        if abs_score > 0.5:
            return 'STRONG'
        if abs_score > 0.2:
            return 'MODERATE'
        return 'WEAK'

    def get_sentiment_color(self, obj):
        score = obj.sentiment_score
        if score is None:
            return 'grey'
        if score > 0.1:
            return 'green'
        if score < -0.1:
            return 'red'
        return 'yellow'


class BacktestResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestResult
        fields = [
            'id', 'run_name', 'start_date', 'end_date', 'cagr',
            'sharpe_ratio', 'max_drawdown', 'benchmark_results', 'created_at'
        ]

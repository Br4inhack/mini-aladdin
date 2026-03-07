"""
Portfolio app models — CRPMS Portfolio Management System.

16 models covering assets, portfolio state, positions, agent outputs,
trades, risk metrics, backtesting, news/sentiment, and system logs.
"""

import logging
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

logger = logging.getLogger('apps.portfolio')


# ─── Asset & Market Data ──────────────────────────────────────────────────────

class Asset(models.Model):
    """Tradeable asset (stock, ETF, crypto, etc.)."""

    ASSET_TYPES = [
        ('equity', 'Equity'),
        ('etf', 'ETF'),
        ('crypto', 'Cryptocurrency'),
        ('bond', 'Bond'),
        ('commodity', 'Commodity'),
    ]

    SECTORS = [
        ('tech', 'Technology'),
        ('finance', 'Finance'),
        ('health', 'Healthcare'),
        ('energy', 'Energy'),
        ('consumer', 'Consumer'),
        ('industrial', 'Industrial'),
        ('materials', 'Materials'),
        ('utilities', 'Utilities'),
        ('real_estate', 'Real Estate'),
        ('comms', 'Communication Services'),
        ('other', 'Other'),
    ]

    ticker = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPES, default='equity')
    sector = models.CharField(max_length=20, choices=SECTORS, default='other')
    exchange = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=10, default='USD')
    is_active = models.BooleanField(default=True, db_index=True)

    # Latest price snapshot (updated by data_ingestion)
    last_price = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    last_price_updated = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ticker']
        verbose_name = 'Asset'
        verbose_name_plural = 'Assets'

    def __str__(self):
        return f"{self.ticker} — {self.name}"


class DataFeed(models.Model):
    """Raw market data feed entry for an asset."""

    SOURCES = [
        ('yfinance', 'Yahoo Finance'),
        ('alpha_vantage', 'Alpha Vantage'),
        ('polygon', 'Polygon.io'),
        ('manual', 'Manual Entry'),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='data_feeds')
    source = models.CharField(max_length=30, choices=SOURCES, default='yfinance')
    timestamp = models.DateTimeField(db_index=True)

    open_price = models.DecimalField(max_digits=18, decimal_places=6)
    high_price = models.DecimalField(max_digits=18, decimal_places=6)
    low_price = models.DecimalField(max_digits=18, decimal_places=6)
    close_price = models.DecimalField(max_digits=18, decimal_places=6)
    volume = models.BigIntegerField(default=0)
    adj_close = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        unique_together = ['asset', 'source', 'timestamp']
        indexes = [
            models.Index(fields=['asset', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.asset.ticker} @ {self.timestamp:%Y-%m-%d %H:%M} (close={self.close_price})"


# ─── Portfolio & Positions ────────────────────────────────────────────────────

class Portfolio(models.Model):
    """A managed portfolio belonging to a user."""

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('archived', 'Archived'),
    ]

    name = models.CharField(max_length=100)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolios')
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    initial_capital = models.DecimalField(max_digits=18, decimal_places=2, default=100000)
    current_cash = models.DecimalField(max_digits=18, decimal_places=2, default=100000)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.owner.username})"

    @property
    def total_value(self):
        """Current portfolio value = cash + sum of position market values."""
        pos_value = sum(p.market_value for p in self.positions.filter(is_open=True))
        return self.current_cash + pos_value


class Position(models.Model):
    """An open or closed position within a portfolio."""

    DIRECTION_CHOICES = [
        ('long', 'Long'),
        ('short', 'Short'),
    ]

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='positions')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='positions')
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default='long')

    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    avg_entry_price = models.DecimalField(max_digits=18, decimal_places=6)
    current_price = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

    is_open = models.BooleanField(default=True, db_index=True)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-opened_at']
        indexes = [
            models.Index(fields=['portfolio', 'is_open']),
            models.Index(fields=['asset', 'is_open']),
        ]

    def __str__(self):
        return f"{self.direction.upper()} {self.quantity} {self.asset.ticker} @ {self.avg_entry_price}"

    @property
    def market_value(self):
        """Current market value of position."""
        if self.current_price is None:
            return self.quantity * self.avg_entry_price
        return self.quantity * self.current_price

    @property
    def unrealised_pnl(self):
        """Unrealised profit/loss."""
        if self.current_price is None:
            return 0
        if self.direction == 'long':
            return self.quantity * (self.current_price - self.avg_entry_price)
        return self.quantity * (self.avg_entry_price - self.current_price)


# ─── Agent Outputs & Signals ──────────────────────────────────────────────────

class AgentOutput(models.Model):
    """Directional signal and confidence score from an individual trading agent."""

    AGENT_NAMES = [
        ('momentum', 'Momentum Agent'),
        ('mean_reversion', 'Mean Reversion Agent'),
        ('sentiment', 'Sentiment Agent'),
        ('macro', 'Macro Agent'),
        ('ml_predictor', 'ML Predictor Agent'),
    ]

    SIGNAL_CHOICES = [
        ('strong_buy', 'Strong Buy'),
        ('buy', 'Buy'),
        ('hold', 'Hold'),
        ('sell', 'Sell'),
        ('strong_sell', 'Strong Sell'),
    ]

    agent_name = models.CharField(max_length=30, choices=AGENT_NAMES, db_index=True)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='agent_outputs')
    signal = models.CharField(max_length=20, choices=SIGNAL_CHOICES)
    confidence = models.FloatField(help_text='0.0 to 1.0')
    reasoning = models.TextField(blank=True, help_text='Human-readable explanation of the signal')
    raw_data = models.JSONField(default=dict, help_text='Raw inputs/features used by the agent')

    generated_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['agent_name', 'asset', 'generated_at']),
            models.Index(fields=['asset', 'generated_at']),
        ]

    def __str__(self):
        return f"{self.agent_name} → {self.asset.ticker}: {self.signal} ({self.confidence:.0%})"


# ─── Portfolio State ──────────────────────────────────────────────────────────

class PortfolioStateSnapshot(models.Model):
    """Periodic snapshot of portfolio state, written by the Portfolio State Engine."""

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='snapshots')
    snapshot_at = models.DateTimeField(default=timezone.now, db_index=True)

    total_value = models.DecimalField(max_digits=18, decimal_places=2)
    cash = models.DecimalField(max_digits=18, decimal_places=2)
    invested_value = models.DecimalField(max_digits=18, decimal_places=2)

    # Allocation breakdown (stored as JSON for flexibility)
    position_weights = models.JSONField(default=dict, help_text='ticker → weight (0-1)')
    sector_exposure = models.JSONField(default=dict, help_text='sector → weight (0-1)')
    risk_budget_used = models.FloatField(default=0.0, help_text='Fraction of risk budget consumed')

    # Performance vs baseline
    daily_return = models.FloatField(null=True, blank=True)
    cumulative_return = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-snapshot_at']
        indexes = [
            models.Index(fields=['portfolio', 'snapshot_at']),
        ]

    def __str__(self):
        return f"Snapshot {self.portfolio.name} @ {self.snapshot_at:%Y-%m-%d %H:%M}"


# ─── Trade Orders & Executions ────────────────────────────────────────────────

class TradeOrder(models.Model):
    """An order generated by the decision engine."""

    ORDER_TYPE = [
        ('market', 'Market'),
        ('limit', 'Limit'),
        ('stop', 'Stop'),
        ('stop_limit', 'Stop Limit'),
    ]

    ORDER_STATUS = [
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('partially_filled', 'Partially Filled'),
        ('filled', 'Filled'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
    ]

    SIDE = [
        ('buy', 'Buy'),
        ('sell', 'Sell'),
    ]

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='orders')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='orders')

    side = models.CharField(max_length=10, choices=SIDE)
    order_type = models.CharField(max_length=20, choices=ORDER_TYPE, default='market')
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    limit_price = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    stop_price = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

    status = models.CharField(max_length=20, choices=ORDER_STATUS, default='pending', db_index=True)
    reason = models.TextField(blank=True, help_text='Why this order was generated')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['portfolio', 'status']),
        ]

    def __str__(self):
        return f"Order {self.side.upper()} {self.quantity} {self.asset.ticker} [{self.status}]"


class TradeExecution(models.Model):
    """Actual execution record for a filled TradeOrder."""

    order = models.OneToOneField(TradeOrder, on_delete=models.CASCADE, related_name='execution')
    executed_at = models.DateTimeField(default=timezone.now, db_index=True)

    executed_quantity = models.DecimalField(max_digits=18, decimal_places=6)
    executed_price = models.DecimalField(max_digits=18, decimal_places=6)
    commission = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    slippage = models.DecimalField(max_digits=18, decimal_places=6, default=0)

    gross_value = models.DecimalField(max_digits=18, decimal_places=2)
    net_value = models.DecimalField(max_digits=18, decimal_places=2)

    broker_ref = models.CharField(max_length=100, blank=True, help_text='Broker trade reference ID')

    class Meta:
        ordering = ['-executed_at']

    def __str__(self):
        return f"Exec {self.order.asset.ticker} {self.executed_quantity} @ {self.executed_price}"


# ─── Risk ────────────────────────────────────────────────────────────────────

class RiskMetrics(models.Model):
    """Computed risk metrics for a portfolio at a point in time."""

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='risk_metrics')
    computed_at = models.DateTimeField(default=timezone.now, db_index=True)

    # Value at Risk
    var_95 = models.FloatField(null=True, blank=True, help_text='95% VaR (fraction of portfolio)')
    var_99 = models.FloatField(null=True, blank=True, help_text='99% VaR (fraction of portfolio)')
    cvar_95 = models.FloatField(null=True, blank=True, help_text='95% CVaR (Expected Shortfall)')

    # Volatility & Beta
    portfolio_volatility = models.FloatField(null=True, blank=True, help_text='Annualised portfolio vol')
    portfolio_beta = models.FloatField(null=True, blank=True, help_text='Beta vs benchmark (SPY)')

    # Drawdown
    max_drawdown = models.FloatField(null=True, blank=True)
    current_drawdown = models.FloatField(null=True, blank=True)

    # Sharpe & Sortino
    sharpe_ratio = models.FloatField(null=True, blank=True)
    sortino_ratio = models.FloatField(null=True, blank=True)

    # Concentration
    herfindahl_index = models.FloatField(null=True, blank=True, help_text='Portfolio concentration index')

    class Meta:
        ordering = ['-computed_at']

    def __str__(self):
        return f"RiskMetrics {self.portfolio.name} @ {self.computed_at:%Y-%m-%d %H:%M}"


class SectorExposure(models.Model):
    """Sector-level exposure breakdown for a portfolio snapshot."""

    snapshot = models.ForeignKey(PortfolioStateSnapshot, on_delete=models.CASCADE, related_name='sector_exposures')
    sector = models.CharField(max_length=30)
    weight = models.FloatField(help_text='Fraction of portfolio NAV in this sector')
    num_positions = models.IntegerField(default=0)

    class Meta:
        unique_together = ['snapshot', 'sector']

    def __str__(self):
        return f"{self.sector}: {self.weight:.1%} ({self.snapshot})"


# ─── Market Regime ────────────────────────────────────────────────────────────

class MarketRegime(models.Model):
    """Detected market regime classification."""

    REGIMES = [
        ('bull', 'Bull Market'),
        ('bear', 'Bear Market'),
        ('sideways', 'Sideways / Ranging'),
        ('high_volatility', 'High Volatility'),
        ('low_volatility', 'Low Volatility'),
        ('crisis', 'Crisis / Risk-Off'),
    ]

    regime = models.CharField(max_length=20, choices=REGIMES)
    confidence = models.FloatField(help_text='Model confidence 0.0-1.0')
    detected_at = models.DateTimeField(default=timezone.now, db_index=True)
    features_used = models.JSONField(default=dict, help_text='Macro features driving this classification')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-detected_at']

    def __str__(self):
        return f"{self.get_regime_display()} @ {self.detected_at:%Y-%m-%d} ({self.confidence:.0%})"


# ─── Backtesting ──────────────────────────────────────────────────────────────

class BacktestRun(models.Model):
    """A backtesting run configuration and status."""

    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    name = models.CharField(max_length=100)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='backtest_runs')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='backtest_runs')

    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(max_digits=18, decimal_places=2)
    commission_rate = models.FloatField(default=0.001)
    slippage_rate = models.FloatField(default=0.0005)

    strategy_config = models.JSONField(default=dict, help_text='Strategy parameters used in this run')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Backtest: {self.name} [{self.status}]"

    @property
    def duration_days(self):
        """Number of calendar days in the backtest window."""
        return (self.end_date - self.start_date).days


class BacktestResult(models.Model):
    """Aggregate performance results for a completed BacktestRun."""

    run = models.OneToOneField(BacktestRun, on_delete=models.CASCADE, related_name='result')

    final_portfolio_value = models.DecimalField(max_digits=18, decimal_places=2)
    total_return = models.FloatField(help_text='Percentage return over the full period')
    annualised_return = models.FloatField(null=True, blank=True)
    benchmark_return = models.FloatField(null=True, blank=True, help_text='SPY return for same period')
    alpha = models.FloatField(null=True, blank=True)

    sharpe_ratio = models.FloatField(null=True, blank=True)
    sortino_ratio = models.FloatField(null=True, blank=True)
    max_drawdown = models.FloatField(null=True, blank=True)
    calmar_ratio = models.FloatField(null=True, blank=True)

    total_trades = models.IntegerField(default=0)
    winning_trades = models.IntegerField(default=0)
    losing_trades = models.IntegerField(default=0)
    win_rate = models.FloatField(null=True, blank=True)
    avg_win = models.FloatField(null=True, blank=True)
    avg_loss = models.FloatField(null=True, blank=True)
    profit_factor = models.FloatField(null=True, blank=True)

    equity_curve = models.JSONField(default=list, help_text='List of {date, value} dicts')

    computed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Result: {self.run.name} — {self.total_return:.2f}% return"


# ─── News & Sentiment ─────────────────────────────────────────────────────────

class NewsItem(models.Model):
    """A news article or social post relevant to one or more assets."""

    SOURCES = [
        ('newsapi', 'NewsAPI'),
        ('reddit', 'Reddit'),
        ('twitter', 'Twitter/X'),
        ('sec', 'SEC Filing'),
        ('rss', 'RSS Feed'),
    ]

    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1000, unique=True)
    source = models.CharField(max_length=20, choices=SOURCES)
    author = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    published_at = models.DateTimeField(db_index=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    assets = models.ManyToManyField(Asset, related_name='news_items', blank=True)
    raw_json = models.JSONField(default=dict, help_text='Original API response payload')

    class Meta:
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['source', 'published_at']),
        ]

    def __str__(self):
        return f"[{self.source}] {self.title[:80]}"


class SentimentScore(models.Model):
    """NLP sentiment score derived from a NewsItem for a specific Asset."""

    LABELS = [
        ('positive', 'Positive'),
        ('neutral', 'Neutral'),
        ('negative', 'Negative'),
    ]

    news_item = models.ForeignKey(NewsItem, on_delete=models.CASCADE, related_name='sentiment_scores')
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='sentiment_scores')

    label = models.CharField(max_length=10, choices=LABELS)
    score = models.FloatField(help_text='Raw sentiment score, typically -1 to +1')
    positive_prob = models.FloatField(default=0.0)
    neutral_prob = models.FloatField(default=0.0)
    negative_prob = models.FloatField(default=0.0)

    model_name = models.CharField(max_length=100, blank=True, help_text='NLP model used')
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['news_item', 'asset']
        ordering = ['-computed_at']

    def __str__(self):
        return f"{self.asset.ticker} | {self.label} ({self.score:+.3f}) — {self.news_item.title[:50]}"


# ─── System Logging ───────────────────────────────────────────────────────────

class SystemLog(models.Model):
    """Structured system event log for CRPMS operations."""

    LEVELS = [
        ('debug', 'Debug'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    COMPONENTS = [
        ('data_ingestion', 'Data Ingestion'),
        ('feature_engine', 'Feature Engine'),
        ('agents', 'Agents'),
        ('portfolio', 'Portfolio'),
        ('decision_engine', 'Decision Engine'),
        ('backtester', 'Backtester'),
        ('dashboard', 'Dashboard'),
        ('celery', 'Celery'),
        ('system', 'System'),
    ]

    level = models.CharField(max_length=10, choices=LEVELS, default='info', db_index=True)
    component = models.CharField(max_length=20, choices=COMPONENTS, default='system', db_index=True)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['level', 'created_at']),
            models.Index(fields=['component', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.level.upper()}] {self.component}: {self.message[:100]}"

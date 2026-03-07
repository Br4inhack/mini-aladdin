"""
Portfolio app models — CRPMS (Cyclical Risk & Portfolio Management System).

16 models covering the watchlist, portfolio state, positions, market data,
feature snapshots, agent outputs, decision logs, news/sentiment, fundamentals,
macro indicators, backtesting, alerts, and system ingestion logs.
"""

from django.db import models
from django.utils import timezone


# ─── 1. Portfolio ──────────────────────────────────────────────────────────────

class Portfolio(models.Model):
    """
    Represents a managed portfolio with capital tracking.
    Stores total and available capital and provides helper methods
    to query allocation percentage, sector exposure, and risk budget usage.
    """

    name = models.CharField(max_length=100)
    total_capital = models.DecimalField(max_digits=15, decimal_places=2)
    available_capital = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Portfolio'
        verbose_name_plural = 'Portfolios'
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.name} (₹{self.total_capital:,.2f})"

    def get_allocation_pct(self):
        """Returns the percentage of capital currently allocated (invested)."""
        if not self.total_capital:
            return 0.0
        invested = self.total_capital - self.available_capital
        return float(invested / self.total_capital * 100)

    def get_sector_exposure(self):
        """
        Returns a dict of sector → allocated capital for all open positions
        belonging to this portfolio.
        """
        exposure = {}
        for pos in self.positions.select_related('watchlist'):
            sector = pos.watchlist.sector or 'Unknown'
            exposure[sector] = exposure.get(sector, 0) + float(
                pos.quantity * (pos.current_price or pos.avg_buy_price)
            )
        return exposure

    def get_risk_budget_used(self):
        """
        Returns the fraction of total capital at risk, computed as
        sum of unrealised losses across all open positions.
        """
        total_loss = sum(
            float(pos.unrealised_pnl)
            for pos in self.positions.all()
            if pos.unrealised_pnl < 0
        )
        if not self.total_capital:
            return 0.0
        return abs(total_loss) / float(self.total_capital)


# ─── 2. Watchlist ──────────────────────────────────────────────────────────────

class Watchlist(models.Model):
    """
    Master list of tradeable instruments tracked by the system.
    Each ticker is unique and acts as the natural key referenced by
    most other models via FK with to_field='ticker'.
    """

    ticker = models.CharField(max_length=20, unique=True, db_index=True)
    company_name = models.CharField(max_length=200, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    sub_sector = models.CharField(max_length=100, blank=True)
    exchange = models.CharField(max_length=10, default='NSE')
    is_active = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ticker']
        verbose_name = 'Watchlist'
        verbose_name_plural = 'Watchlist'
        indexes = [
            models.Index(fields=['ticker']),
            models.Index(fields=['sector']),
        ]

    def __str__(self):
        return f"{self.ticker} — {self.company_name or 'N/A'} ({self.exchange})"


# ─── 3. Position ───────────────────────────────────────────────────────────────

class Position(models.Model):
    """
    An active or historical position held in a portfolio for a given instrument.
    Tracks quantity, average buy price, current price, allocation percentage,
    and unrealised P&L. A portfolio cannot hold duplicate positions in the same
    instrument (enforced by unique_together).
    """

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='positions',
    )
    watchlist = models.ForeignKey(
        Watchlist,
        on_delete=models.PROTECT,
        to_field='ticker',
        related_name='positions',
    )
    quantity = models.IntegerField()
    avg_buy_price = models.DecimalField(max_digits=12, decimal_places=2)
    current_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    allocation_pct = models.FloatField(default=0)
    unrealised_pnl = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['portfolio', 'watchlist']
        ordering = ['-created_at']
        verbose_name = 'Position'
        verbose_name_plural = 'Positions'
        indexes = [
            models.Index(fields=['portfolio']),
        ]

    def __str__(self):
        return (
            f"{self.watchlist_id} × {self.quantity} "
            f"@ ₹{self.avg_buy_price} [{self.portfolio}]"
        )

    @property
    def ticker(self):
        """Convenience shortcut returning the watchlist ticker symbol."""
        return self.watchlist_id  # watchlist FK stored as ticker value

    @property
    def cost_basis(self):
        """Total cost of acquiring this position."""
        return self.quantity * self.avg_buy_price


# ─── 4. SectorMapping ──────────────────────────────────────────────────────────

class SectorMapping(models.Model):
    """
    Maps a watchlist ticker to a sector (and optional sub-sector).
    Used by the sector exposure calculations and risk engine to
    group positions for concentration analysis.
    """

    sector = models.CharField(max_length=100)
    sub_sector = models.CharField(max_length=100, blank=True)
    ticker = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='sector_mappings',
    )

    class Meta:
        verbose_name = 'Sector Mapping'
        verbose_name_plural = 'Sector Mappings'
        indexes = [
            models.Index(fields=['sector']),
        ]

    def __str__(self):
        return f"{self.ticker_id} → {self.sector} / {self.sub_sector or '—'}"


# ─── 5. PriceHistory ───────────────────────────────────────────────────────────

class PriceHistory(models.Model):
    """
    Daily OHLCV price bars for a watchlist instrument.
    Used by the feature engine, backtester, and charting subsystems.
    Each ticker-date pair is unique to prevent duplicate ingestion.
    """

    ticker = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='price_history',
    )
    date = models.DateField()
    open = models.DecimalField(max_digits=12, decimal_places=2)
    high = models.DecimalField(max_digits=12, decimal_places=2)
    low = models.DecimalField(max_digits=12, decimal_places=2)
    close = models.DecimalField(max_digits=12, decimal_places=2)
    volume = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['ticker', 'date']
        ordering = ['-date']
        verbose_name = 'Price History'
        verbose_name_plural = 'Price History'
        indexes = [
            models.Index(fields=['ticker', 'date']),
        ]

    def __str__(self):
        return f"{self.ticker_id} | {self.date} | C={self.close}"


# ─── 6. FeatureSnapshot ────────────────────────────────────────────────────────

class FeatureSnapshot(models.Model):
    """
    A point-in-time snapshot of all computed ML features for a ticker,
    organised into four JSON buckets: risk, sentiment, fundamental,
    and opportunity. Consumed by agent models for scoring.
    """

    ticker = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='feature_snapshots',
    )
    date = models.DateField()
    risk_features = models.JSONField(default=dict)
    sentiment_features = models.JSONField(default=dict)
    fundamental_features = models.JSONField(default=dict)
    opportunity_features = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['ticker', 'date']
        ordering = ['-date']
        verbose_name = 'Feature Snapshot'
        verbose_name_plural = 'Feature Snapshots'
        indexes = [
            models.Index(fields=['ticker', 'date']),
        ]

    def __str__(self):
        return f"FeatureSnapshot {self.ticker_id} | {self.date}"


# ─── 7. AgentOutput ────────────────────────────────────────────────────────────

class AgentOutput(models.Model):
    """
    Scored output from one of the four CRPMS risk/opportunity agents.
    Stores the numeric score, categorical band, feature flags, and raw data
    payload. Records are marked stale once they exceed a configurable threshold.
    """

    class AgentName(models.TextChoices):
        MARKET_RISK = 'market_risk', 'Market Risk'
        SENTIMENT = 'sentiment', 'Sentiment'
        FUNDAMENTAL = 'fundamental', 'Fundamental'
        OPPORTUNITY = 'opportunity', 'Opportunity'

    class Band(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        CRITICAL = 'CRITICAL', 'Critical'

    ticker = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='agent_outputs',
    )
    agent_name = models.CharField(max_length=20, choices=AgentName.choices)
    score = models.FloatField()
    band = models.CharField(
        max_length=10, choices=Band.choices, null=True, blank=True
    )
    flags = models.JSONField(default=dict)
    raw_data = models.JSONField(default=dict)
    is_stale = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Agent Output'
        verbose_name_plural = 'Agent Outputs'
        indexes = [
            models.Index(fields=['ticker', 'agent_name', 'timestamp']),
        ]

    def __str__(self):
        return (
            f"{self.agent_name} | {self.ticker_id} | "
            f"score={self.score:.2f} band={self.band or '—'}"
        )

    def check_stale(self, threshold_hours: int = 1) -> bool:
        """
        Returns True if this output is older than ``threshold_hours`` hours,
        and also sets ``is_stale=True`` on the instance (does NOT save).
        """
        age = timezone.now() - self.timestamp
        stale = age.total_seconds() > threshold_hours * 3600
        if stale:
            self.is_stale = True
        return stale


# ─── 8. DecisionLog ────────────────────────────────────────────────────────────

class DecisionLog(models.Model):
    """
    Records each portfolio decision made by the decision engine for a ticker,
    including the action taken, confidence score, human-readable reasoning,
    and the full input signal payload that drove the decision.
    """

    class Action(models.TextChoices):
        HOLD = 'HOLD', 'Hold'
        REDUCE = 'REDUCE', 'Reduce'
        EXIT = 'EXIT', 'Exit'
        INCREASE = 'INCREASE', 'Increase'
        REALLOCATE = 'REALLOCATE', 'Reallocate'

    ticker = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='decision_logs',
    )
    action = models.CharField(max_length=15, choices=Action.choices)
    confidence_score = models.FloatField(default=0)
    reasoning_text = models.TextField(blank=True)
    input_signals = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Decision Log'
        verbose_name_plural = 'Decision Logs'
        indexes = [
            models.Index(fields=['ticker', 'timestamp']),
        ]

    def __str__(self):
        return (
            f"{self.action} {self.ticker_id} "
            f"(conf={self.confidence_score:.2f}) @ {self.timestamp:%Y-%m-%d %H:%M}"
        )


# ─── 9. NewsArticle ────────────────────────────────────────────────────────────

class NewsArticle(models.Model):
    """
    A news article associated with a watchlist ticker.
    Stores headline, source, URL, sentiment score, and timestamps.
    Deduplication is enforced via a SHA-256 content_hash of the article body.
    """

    ticker_tag = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='news_articles',
    )
    headline = models.TextField()
    source = models.CharField(max_length=100, blank=True)
    url = models.URLField(max_length=500, blank=True)
    sentiment_score = models.FloatField(null=True, blank=True)
    published_at = models.DateTimeField()
    processed_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ['-published_at']
        verbose_name = 'News Article'
        verbose_name_plural = 'News Articles'
        indexes = [
            models.Index(fields=['ticker_tag', 'published_at']),
        ]

    def __str__(self):
        return f"[{self.ticker_tag_id}] {self.headline[:80]}"


# ─── 10. SocialPost ────────────────────────────────────────────────────────────

class SocialPost(models.Model):
    """
    A social media post (Reddit, StockTwits, etc.) mentioning a ticker.
    Stores the raw text, platform, sentiment score, and engagement metrics.
    Deduplication is enforced via content_hash.
    """

    class Platform(models.TextChoices):
        REDDIT = 'reddit', 'Reddit'
        STOCKTWITS = 'stocktwits', 'StockTwits'

    ticker_tag = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='social_posts',
    )
    platform = models.CharField(max_length=15, choices=Platform.choices)
    text = models.TextField()
    sentiment_score = models.FloatField(null=True, blank=True)
    mention_count = models.IntegerField(default=1)
    upvotes = models.IntegerField(default=0)
    content_hash = models.CharField(max_length=64, unique=True)
    posted_at = models.DateTimeField()

    class Meta:
        ordering = ['-posted_at']
        verbose_name = 'Social Post'
        verbose_name_plural = 'Social Posts'
        indexes = [
            models.Index(fields=['ticker_tag', 'posted_at']),
        ]

    def __str__(self):
        return (
            f"[{self.platform}] {self.ticker_tag_id} "
            f"@ {self.posted_at:%Y-%m-%d} — {self.text[:60]}"
        )


# ─── 11. FundamentalData ───────────────────────────────────────────────────────

class FundamentalData(models.Model):
    """
    Quarterly or annual fundamental financial data for a watchlist ticker.
    Covers revenue, EPS, debt ratio, ROE, P/E ratio, net margin, and
    promoter pledge percentage. Each ticker-period combination is unique.
    """

    ticker = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='fundamental_data',
    )
    period = models.CharField(max_length=20)  # e.g. 'Q3FY25', 'FY2024'
    revenue = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    eps = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    debt_ratio = models.FloatField(null=True, blank=True)
    roe = models.FloatField(null=True, blank=True)
    pe_ratio = models.FloatField(null=True, blank=True)
    net_margin = models.FloatField(null=True, blank=True)
    promoter_pledge_pct = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['ticker', 'period']
        ordering = ['-period']
        verbose_name = 'Fundamental Data'
        verbose_name_plural = 'Fundamental Data'
        indexes = [
            models.Index(fields=['ticker', 'period']),
        ]

    def __str__(self):
        return f"{self.ticker_id} | {self.period} | EPS={self.eps}"


# ─── 12. MacroIndicator ────────────────────────────────────────────────────────

class MacroIndicator(models.Model):
    """
    A macroeconomic indicator reading (e.g. CPI, repo rate, GDP growth)
    at a specific date. Used by the macro risk agent to assess the
    broad market environment and adjust portfolio risk budgets.
    """

    indicator_name = models.CharField(max_length=100)
    value = models.FloatField()
    date = models.DateField()
    source = models.CharField(max_length=50, blank=True)

    class Meta:
        unique_together = ['indicator_name', 'date']
        ordering = ['-date']
        verbose_name = 'Macro Indicator'
        verbose_name_plural = 'Macro Indicators'
        indexes = [
            models.Index(fields=['indicator_name', 'date']),
        ]

    def __str__(self):
        return f"{self.indicator_name} = {self.value} @ {self.date}"


# ─── 13. PortfolioStateSnapshot ────────────────────────────────────────────────

class PortfolioStateSnapshot(models.Model):
    """
    A periodic serialised snapshot of the full portfolio state, stored as
    a JSON blob. Used by the dashboard and backtester to reconstruct
    portfolio history without re-running all transactions.
    """

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='state_snapshots',
    )
    state_data = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Portfolio State Snapshot'
        verbose_name_plural = 'Portfolio State Snapshots'
        indexes = [
            models.Index(fields=['portfolio', 'timestamp']),
        ]

    def __str__(self):
        return f"Snapshot {self.portfolio} @ {self.timestamp:%Y-%m-%d %H:%M}"


# ─── 14. BacktestResult ────────────────────────────────────────────────────────

class BacktestResult(models.Model):
    """
    Aggregate performance results for a completed backtest run.
    Stores Sharpe ratio, CAGR, max drawdown, win rate, capital utilisation,
    the strategy configuration used, and benchmark comparison results.
    """

    run_name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    starting_capital = models.DecimalField(max_digits=15, decimal_places=2)
    sharpe_ratio = models.FloatField(null=True, blank=True)
    cagr = models.FloatField(null=True, blank=True)
    max_drawdown = models.FloatField(null=True, blank=True)
    win_rate = models.FloatField(null=True, blank=True)
    capital_utilisation = models.FloatField(null=True, blank=True)
    config = models.JSONField(default=dict)
    benchmark_results = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Backtest Result'
        verbose_name_plural = 'Backtest Results'
        indexes = [
            models.Index(fields=['run_name']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return (
            f"Backtest '{self.run_name}' "
            f"{self.start_date} → {self.end_date} "
            f"(Sharpe={self.sharpe_ratio}, CAGR={self.cagr})"
        )


# ─── 15. Alert ─────────────────────────────────────────────────────────────────

class Alert(models.Model):
    """
    A system-generated alert for a watchlist ticker, categorised by type
    (risk critical, high risk, opportunity, stop-loss, or event risk).
    Alerts can be acknowledged by the user through the dashboard.
    """

    class AlertType(models.TextChoices):
        RISK_CRITICAL = 'RISK_CRITICAL', 'Risk Critical'
        RISK_HIGH = 'RISK_HIGH', 'Risk High'
        OPPORTUNITY = 'OPPORTUNITY', 'Opportunity'
        STOP_LOSS = 'STOP_LOSS', 'Stop Loss'
        EVENT_RISK = 'EVENT_RISK', 'Event Risk'

    ticker = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        to_field='ticker',
        related_name='alerts',
    )
    alert_type = models.CharField(max_length=15, choices=AlertType.choices)
    message = models.TextField()
    threshold_breached = models.FloatField(null=True, blank=True)
    is_acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Alert'
        verbose_name_plural = 'Alerts'
        indexes = [
            models.Index(fields=['ticker', 'alert_type', 'created_at']),
        ]

    def __str__(self):
        return (
            f"[{self.alert_type}] {self.ticker_id}: "
            f"{self.message[:80]} "
            f"{'✓' if self.is_acknowledged else '⚑'}"
        )


# ─── 16. DataIngestionLog ──────────────────────────────────────────────────────

class DataIngestionLog(models.Model):
    """
    Audit log for every data ingestion task run by the system.
    Records the source, target ticker (if applicable), outcome status,
    error details, and the number of records successfully fetched.
    """

    class Status(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Success'
        PARTIAL = 'PARTIAL', 'Partial'
        FAILED = 'FAILED', 'Failed'

    source_name = models.CharField(max_length=50)
    ticker = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error_message = models.TextField(blank=True)
    records_fetched = models.IntegerField(default=0)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Data Ingestion Log'
        verbose_name_plural = 'Data Ingestion Logs'
        indexes = [
            models.Index(fields=['source_name', 'timestamp']),
            models.Index(fields=['status', 'timestamp']),
        ]

    def __str__(self):
        return (
            f"[{self.status}] {self.source_name} "
            f"{'(' + self.ticker + ')' if self.ticker else ''} "
            f"@ {self.timestamp:%Y-%m-%d %H:%M} — {self.records_fetched} records"
        )

"""
Admin registration for the portfolio app — CRPMS.
All 16 models are registered with @admin.register, sensible list_display,
list_filter where useful, and search_fields on key text fields.
"""

from django.contrib import admin
from .models import (
    Portfolio,
    Watchlist,
    Position,
    SectorMapping,
    PriceHistory,
    FeatureSnapshot,
    AgentOutput,
    DecisionLog,
    NewsArticle,
    SocialPost,
    FundamentalData,
    MacroIndicator,
    PortfolioStateSnapshot,
    BacktestResult,
    Alert,
    DataIngestionLog,
)


# ─── 1. Portfolio ──────────────────────────────────────────────────────────────

@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'total_capital', 'available_capital',
        'created_at', 'updated_at',
    ]
    search_fields = ['name']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']


# ─── 2. Watchlist ──────────────────────────────────────────────────────────────

@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = [
        'ticker', 'company_name', 'sector', 'sub_sector',
        'exchange', 'is_active', 'added_at',
    ]
    list_filter = ['sector', 'exchange', 'is_active']
    search_fields = ['ticker', 'company_name']
    ordering = ['ticker']
    readonly_fields = ['added_at']


# ─── 3. Position ───────────────────────────────────────────────────────────────

@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'portfolio', 'watchlist', 'quantity',
        'avg_buy_price', 'current_price', 'allocation_pct',
        'unrealised_pnl', 'updated_at',
    ]
    list_filter = ['portfolio']
    search_fields = ['watchlist__ticker', 'portfolio__name']
    readonly_fields = ['created_at', 'updated_at']


# ─── 4. SectorMapping ──────────────────────────────────────────────────────────

@admin.register(SectorMapping)
class SectorMappingAdmin(admin.ModelAdmin):
    list_display = ['ticker', 'sector', 'sub_sector']
    list_filter = ['sector']
    search_fields = ['ticker__ticker', 'sector']


# ─── 5. PriceHistory ───────────────────────────────────────────────────────────

@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = [
        'ticker', 'date', 'open', 'high', 'low', 'close', 'volume',
    ]
    list_filter = ['ticker']
    search_fields = ['ticker__ticker']
    ordering = ['-date']
    date_hierarchy = 'date'
    readonly_fields = ['created_at']


# ─── 6. FeatureSnapshot ────────────────────────────────────────────────────────

@admin.register(FeatureSnapshot)
class FeatureSnapshotAdmin(admin.ModelAdmin):
    list_display = ['ticker', 'date', 'created_at']
    list_filter = ['ticker']
    search_fields = ['ticker__ticker']
    ordering = ['-date']
    date_hierarchy = 'date'
    readonly_fields = ['created_at']


# ─── 7. AgentOutput ────────────────────────────────────────────────────────────

@admin.register(AgentOutput)
class AgentOutputAdmin(admin.ModelAdmin):
    list_display = [
        'ticker', 'agent_name', 'score', 'band',
        'is_stale', 'timestamp',
    ]
    list_filter = ['agent_name', 'band', 'is_stale']
    search_fields = ['ticker__ticker']
    ordering = ['-timestamp']
    readonly_fields = ['timestamp']


# ─── 8. DecisionLog ────────────────────────────────────────────────────────────

@admin.register(DecisionLog)
class DecisionLogAdmin(admin.ModelAdmin):
    list_display = [
        'ticker', 'action', 'confidence_score', 'timestamp',
    ]
    list_filter = ['action']
    search_fields = ['ticker__ticker']
    ordering = ['-timestamp']
    readonly_fields = ['timestamp']


# ─── 9. NewsArticle ────────────────────────────────────────────────────────────

@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = [
        'ticker_tag', 'headline', 'source', 'sentiment_score',
        'published_at', 'processed_at',
    ]
    list_filter = ['source', 'ticker_tag']
    search_fields = ['ticker_tag__ticker', 'headline', 'source']
    ordering = ['-published_at']
    date_hierarchy = 'published_at'
    readonly_fields = ['content_hash']


# ─── 10. SocialPost ────────────────────────────────────────────────────────────

@admin.register(SocialPost)
class SocialPostAdmin(admin.ModelAdmin):
    list_display = [
        'ticker_tag', 'platform', 'sentiment_score',
        'mention_count', 'upvotes', 'posted_at',
    ]
    list_filter = ['platform', 'ticker_tag']
    search_fields = ['ticker_tag__ticker', 'text']
    ordering = ['-posted_at']
    readonly_fields = ['content_hash']


# ─── 11. FundamentalData ───────────────────────────────────────────────────────

@admin.register(FundamentalData)
class FundamentalDataAdmin(admin.ModelAdmin):
    list_display = [
        'ticker', 'period', 'revenue', 'eps',
        'debt_ratio', 'roe', 'pe_ratio', 'net_margin',
        'promoter_pledge_pct', 'updated_at',
    ]
    list_filter = ['ticker']
    search_fields = ['ticker__ticker', 'period']
    ordering = ['-period']
    readonly_fields = ['updated_at']


# ─── 12. MacroIndicator ────────────────────────────────────────────────────────

@admin.register(MacroIndicator)
class MacroIndicatorAdmin(admin.ModelAdmin):
    list_display = ['indicator_name', 'value', 'date', 'source']
    list_filter = ['indicator_name', 'source']
    search_fields = ['indicator_name', 'source']
    ordering = ['-date']
    date_hierarchy = 'date'


# ─── 13. PortfolioStateSnapshot ────────────────────────────────────────────────

@admin.register(PortfolioStateSnapshot)
class PortfolioStateSnapshotAdmin(admin.ModelAdmin):
    list_display = ['id', 'portfolio', 'timestamp']
    list_filter = ['portfolio']
    ordering = ['-timestamp']
    readonly_fields = ['timestamp']


# ─── 14. BacktestResult ────────────────────────────────────────────────────────

@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    list_display = [
        'run_name', 'start_date', 'end_date', 'starting_capital',
        'sharpe_ratio', 'cagr', 'max_drawdown', 'win_rate',
        'capital_utilisation', 'created_at',
    ]
    search_fields = ['run_name']
    ordering = ['-created_at']
    readonly_fields = ['created_at']


# ─── 15. Alert ─────────────────────────────────────────────────────────────────

@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = [
        'ticker', 'alert_type', 'message', 'threshold_breached',
        'is_acknowledged', 'created_at',
    ]
    list_filter = ['alert_type', 'is_acknowledged']
    search_fields = ['ticker__ticker', 'message']
    ordering = ['-created_at']
    readonly_fields = ['created_at']


# ─── 16. DataIngestionLog ──────────────────────────────────────────────────────

@admin.register(DataIngestionLog)
class DataIngestionLogAdmin(admin.ModelAdmin):
    list_display = [
        'source_name', 'ticker', 'status',
        'records_fetched', 'timestamp',
    ]
    list_filter = ['status', 'source_name']
    search_fields = ['source_name', 'ticker']
    ordering = ['-timestamp']
    readonly_fields = ['timestamp']

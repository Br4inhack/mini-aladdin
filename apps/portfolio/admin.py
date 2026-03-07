"""
Admin registration for the portfolio app.
All 16 models are registered with sensible list views, filters, and search.
"""

from django.contrib import admin
from .models import (
    Asset,
    DataFeed,
    Portfolio,
    Position,
    AgentOutput,
    PortfolioStateSnapshot,
    TradeOrder,
    TradeExecution,
    RiskMetrics,
    SectorExposure,
    MarketRegime,
    BacktestRun,
    BacktestResult,
    NewsItem,
    SentimentScore,
    SystemLog,
)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ['ticker', 'name', 'asset_type', 'sector', 'exchange', 'currency', 'last_price', 'is_active']
    list_filter = ['asset_type', 'sector', 'is_active', 'currency']
    search_fields = ['ticker', 'name']
    ordering = ['ticker']
    readonly_fields = ['last_price_updated', 'created_at', 'updated_at']


@admin.register(DataFeed)
class DataFeedAdmin(admin.ModelAdmin):
    list_display = ['asset', 'source', 'timestamp', 'open_price', 'close_price', 'volume']
    list_filter = ['source', 'asset__sector']
    search_fields = ['asset__ticker']
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'
    readonly_fields = ['created_at']


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'status', 'initial_capital', 'current_cash', 'created_at']
    list_filter = ['status']
    search_fields = ['name', 'owner__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'asset', 'direction', 'quantity', 'avg_entry_price', 'current_price', 'is_open', 'opened_at']
    list_filter = ['direction', 'is_open', 'asset__sector']
    search_fields = ['asset__ticker', 'portfolio__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(AgentOutput)
class AgentOutputAdmin(admin.ModelAdmin):
    list_display = ['agent_name', 'asset', 'signal', 'confidence', 'generated_at', 'is_stale']
    list_filter = ['agent_name', 'signal', 'is_stale']
    search_fields = ['asset__ticker']
    ordering = ['-generated_at']
    readonly_fields = ['generated_at']


@admin.register(PortfolioStateSnapshot)
class PortfolioStateSnapshotAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'snapshot_at', 'total_value', 'cash', 'risk_budget_used', 'daily_return']
    list_filter = ['portfolio']
    ordering = ['-snapshot_at']
    date_hierarchy = 'snapshot_at'
    readonly_fields = ['created_at']


@admin.register(TradeOrder)
class TradeOrderAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'asset', 'side', 'order_type', 'quantity', 'limit_price', 'status', 'created_at']
    list_filter = ['side', 'order_type', 'status']
    search_fields = ['asset__ticker', 'portfolio__name']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TradeExecution)
class TradeExecutionAdmin(admin.ModelAdmin):
    list_display = ['order', 'executed_at', 'executed_quantity', 'executed_price', 'commission', 'net_value']
    ordering = ['-executed_at']
    readonly_fields = ['executed_at']


@admin.register(RiskMetrics)
class RiskMetricsAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'computed_at', 'var_95', 'portfolio_volatility', 'sharpe_ratio', 'max_drawdown']
    list_filter = ['portfolio']
    ordering = ['-computed_at']
    readonly_fields = ['computed_at']


@admin.register(SectorExposure)
class SectorExposureAdmin(admin.ModelAdmin):
    list_display = ['snapshot', 'sector', 'weight', 'num_positions']
    list_filter = ['sector']


@admin.register(MarketRegime)
class MarketRegimeAdmin(admin.ModelAdmin):
    list_display = ['regime', 'confidence', 'detected_at']
    list_filter = ['regime']
    ordering = ['-detected_at']
    readonly_fields = ['detected_at']


@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ['name', 'portfolio', 'start_date', 'end_date', 'initial_capital', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['name', 'portfolio__name']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'started_at', 'completed_at']


@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    list_display = ['run', 'total_return', 'sharpe_ratio', 'max_drawdown', 'win_rate', 'total_trades']
    ordering = ['-computed_at']
    readonly_fields = ['computed_at']


@admin.register(NewsItem)
class NewsItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'source', 'author', 'published_at', 'fetched_at']
    list_filter = ['source']
    search_fields = ['title', 'author']
    ordering = ['-published_at']
    date_hierarchy = 'published_at'
    filter_horizontal = ['assets']
    readonly_fields = ['fetched_at']


@admin.register(SentimentScore)
class SentimentScoreAdmin(admin.ModelAdmin):
    list_display = ['asset', 'label', 'score', 'model_name', 'computed_at', 'news_item']
    list_filter = ['label', 'asset__sector']
    search_fields = ['asset__ticker']
    ordering = ['-computed_at']
    readonly_fields = ['computed_at']


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ['level', 'component', 'message', 'created_at']
    list_filter = ['level', 'component']
    search_fields = ['message']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at']

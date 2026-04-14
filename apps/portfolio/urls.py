"""
DRF URL routing for the Portfolio API endpoints.
"""
from django.urls import path
from apps.portfolio import api_views
from apps.portfolio import export_views

urlpatterns = [
    path('portfolio/<int:portfolio_id>/summary/', api_views.PortfolioSummaryView.as_view(), name='api-portfolio-summary'),
    path('portfolio/<int:portfolio_id>/positions/', api_views.PositionListView.as_view(), name='api-positions'),
    path('portfolio/<int:portfolio_id>/risk/', api_views.RiskView.as_view(), name='api-risk'),
    path('portfolio/<int:portfolio_id>/decisions/', api_views.DecisionView.as_view(), name='api-decisions'),
    path('portfolio/<int:portfolio_id>/state-snapshot/', api_views.StateSnapshotView.as_view(), name='api-state-snapshot'),
    path('portfolio/<int:portfolio_id>/equity-curve/', api_views.PortfolioEquityCurveView.as_view(), name='api-equity-curve'),
    path('portfolio/<int:portfolio_id>/alerts/', api_views.AlertListView.as_view(), name='api-alerts'),
    path('portfolio/<int:portfolio_id>/alerts/history/', api_views.AlertHistoryView.as_view(), name='api-alerts-history'),
    path('portfolio/<int:portfolio_id>/alerts/stats/', api_views.AlertStatsView.as_view(), name='api-alerts-stats'),
    path('portfolio/<int:portfolio_id>/alerts/<int:alert_id>/acknowledge/', api_views.AlertAcknowledgeView.as_view(), name='api-alerts-acknowledge'),
    path('portfolio/<int:portfolio_id>/price-history/<str:ticker_symbol>/', api_views.PriceHistoryView.as_view(), name='api-price-history'),
    path('portfolio/<int:portfolio_id>/news/<str:ticker_symbol>/', api_views.NewsArticleView.as_view(), name='api-news'),
    path('portfolio/<int:portfolio_id>/backtest-results/', api_views.BacktestResultListView.as_view(), name='api-backtest-list'),
    path('portfolio/<int:portfolio_id>/backtest-results/<int:backtest_id>/', api_views.BacktestDetailView.as_view(), name='api-backtest-detail'),
    path('portfolio/<int:portfolio_id>/run-backtest/', api_views.RunBacktestView.as_view(), name='api-run-backtest'),
    path('portfolio/<int:portfolio_id>/trade-logs/', api_views.TradeLogAPIView.as_view(), name='api-trade-logs'),
    
    path('portfolio/<int:portfolio_id>/export/positions/csv/', export_views.ExportPositionsCSVView.as_view(), name='api-export-positions'),
    path('portfolio/<int:portfolio_id>/export/trades/csv/', export_views.ExportTradeLogCSVView.as_view(), name='api-export-trades'),

    path('watchlist/opportunities/', api_views.WatchlistOpportunitiesView.as_view(), name='api-watchlist-opportunities'),
    path('asset/<str:ticker_symbol>/history/', api_views.AssetHistoryView.as_view(), name='api-asset-history'),
    path('portfolio/<int:portfolio_id>/sentiment-trend/<str:ticker_symbol>/', api_views.SentimentTrendView.as_view(), name='api-sentiment-trend'),
    path('portfolio/<int:portfolio_id>/sector-exposure/', api_views.SectorExposureView.as_view(), name='api-sector-exposure'),
    path('portfolio/<int:portfolio_id>/pnl-trend/', api_views.PnLTrendView.as_view(), name='api-pnl-trend'),

        path('portfolio/<int:portfolio_id>/macro-indicators/', api_views.MacroIndicatorView.as_view(), name='api-macro-indicators'),
    path('health/', api_views.HealthCheckAPIView.as_view(), name='api-health'),
]

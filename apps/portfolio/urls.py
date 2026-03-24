"""
DRF URL routing for the Portfolio API endpoints.
"""
from django.urls import path
from apps.portfolio import api_views

urlpatterns = [
    path('portfolio/', api_views.PortfolioAPIView.as_view(), name='api-portfolio'),
    path('positions/', api_views.PositionsAPIView.as_view(), name='api-positions'),
    path('decisions/', api_views.DecisionAPIView.as_view(), name='api-decisions'),
    path('agents/', api_views.AgentOutputAPIView.as_view(), name='api-agents'),
    path('opportunities/', api_views.OpportunityAPIView.as_view(), name='api-opportunities'),
    path('alerts/', api_views.AlertAPIView.as_view(), name='api-alerts'),
    path('alerts/<int:pk>/acknowledge/', api_views.AlertAcknowledgeAPIView.as_view(), name='api-alerts-acknowledge'),
    path('backtest/', api_views.BacktestListAPIView.as_view(), name='api-backtest-list'),
    path('backtest/run/', api_views.BacktestRunAPIView.as_view(), name='api-backtest-run'),
    path('suggestion/', api_views.PortfolioSuggestionAPIView.as_view(), name='api-suggestion'),
    path('health/', api_views.HealthCheckAPIView.as_view(), name='api-health'),
]

"""
URL routing for the CRPMS Dashboard.
"""

from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.DashboardIndexView.as_view(), name='index'),
    path('portfolio/<int:portfolio_id>/', views.PortfolioDetailView.as_view(), name='portfolio'),
    path('asset/<str:ticker>/', views.AssetDetailView.as_view(), name='asset_detail'),
    path('watchlist/', views.WatchlistView.as_view(), name='watchlist'),
    path('decisions/', views.TradeLogView.as_view(), name='trade_logs'),
    path('backtest/', views.BacktestView.as_view(), name='backtest'),
    path('alerts/', views.AlertHistoryView.as_view(), name='alerts'),
    path('settings/', views.SettingsView.as_view(), name='settings'),
]

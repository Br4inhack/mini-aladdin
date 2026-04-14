"""
Dashboard view controllers for CRPMS.
Simple template renderers — all data is fetched by JavaScript from the REST API.
"""

from django.shortcuts import render, redirect
from django.views import View


class IndexRedirectView(View):
    def get(self, request):
        return redirect('/dashboard/')


class DashboardIndexView(View):
    def get(self, request):
        return render(request, 'dashboard/index.html', {'portfolio_id': 1})


class PortfolioDetailView(View):
    def get(self, request, portfolio_id):
        return render(request, 'dashboard/portfolio.html', {'portfolio_id': portfolio_id})


class WatchlistView(View):
    def get(self, request):
        return render(request, 'dashboard/watchlist.html', {'portfolio_id': 1})


class AssetDetailView(View):
    def get(self, request, ticker):
        return render(request, 'dashboard/asset_detail.html', {'portfolio_id': 1, 'ticker': ticker})


class TradeLogView(View):
    def get(self, request):
        return render(request, 'dashboard/trade_logs.html', {'portfolio_id': 1})


class BacktestView(View):
    def get(self, request):
        return render(request, 'dashboard/backtest.html', {'portfolio_id': 1})


class AlertHistoryView(View):
    def get(self, request):
        return render(request, 'dashboard/alerts.html', {'portfolio_id': 1})

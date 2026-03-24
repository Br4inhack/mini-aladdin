"""
apps/dashboard/routing.py

WebSocket URL routing for the dashboard app.
Imported by config/asgi.py — add new consumer routes here.
"""

from django.urls import re_path

from apps.dashboard.consumers import PortfolioConsumer

websocket_urlpatterns = [
    re_path(r'ws/portfolio/(?P<portfolio_id>\d+)/$', PortfolioConsumer.as_asgi()),
]

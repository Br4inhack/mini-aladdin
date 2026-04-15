"""
urls.py — Person 4 (Sentiment Agent)
=====================================
URL routing for the sentiment analysis API.

This file is included in config/urls.py under the 'api/sentiment/' prefix.
Final URL: POST /api/sentiment/analyze/
"""

from django.urls import path
from .api_views import SentimentAnalysisView

app_name = "sentiment_agent"

urlpatterns = [
    # POST /api/sentiment/analyze/
    # Accepts: {"companies": ["Tata Motors", "Reliance Industries"]}
    # Returns: full sentiment + decision result per company
    path(
        "analyze/",
        SentimentAnalysisView.as_view(),
        name="sentiment-analyze",
    ),
]

"""
apps.py — Person 4 (Sentiment Agent)
======================================
Standard Django AppConfig for the sentiment_agent sub-app.

App name must be the full dotted path: 'apps.agents.sentiment_agent'
This is what you add to INSTALLED_APPS in config/settings.py.
"""

from django.apps import AppConfig


class SentimentAgentConfig(AppConfig):
    """
    Django application configuration for Person 4's sentiment analysis module.
    The full dotted app name is required because this is a sub-app nested
    inside apps/agents/.
    """

    default_auto_field = "django.db.models.BigAutoField"

    # Full dotted path — must match the directory structure exactly
    name = "apps.agents.sentiment_agent"

    # Human-readable name shown in Django admin
    verbose_name = "Sentiment Agent (Person 4)"

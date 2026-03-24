"""
Centralised Celery Beat Schedule Configuration.
Maps task execution to specific crontab definitions.
"""

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # ─── Every 15 Minutes (Market Hours: Mon-Fri) ─────────────────────────────
    'fetch_market_data_every_15m': {
        'task': 'apps.data_ingestion.tasks.fetch_market_data',
        'schedule': crontab(minute='*/15', day_of_week='1-5'),
    },
    'run_market_risk_agent_every_15m': {
        'task': 'apps.agents.tasks.run_market_risk_agent',
        'schedule': crontab(minute='*/15', day_of_week='1-5'),
    },
    'run_opportunity_agent_every_15m': {
        'task': 'apps.agents.tasks.run_opportunity_agent',
        'schedule': crontab(minute='*/15', day_of_week='1-5'),
    },
    'update_portfolio_state_every_15m': {
        'task': 'apps.portfolio.tasks.update_portfolio_state',
        'schedule': crontab(minute='*/15', day_of_week='1-5'),
    },

    # ─── Every 1 Hour (Market Hours: Mon-Fri) ─────────────────────────────────
    'fetch_news_data_hourly': {
        'task': 'apps.data_ingestion.tasks.fetch_news_data',
        'schedule': crontab(minute='0', day_of_week='1-5'),
    },
    'run_sentiment_agent_hourly': {
        'task': 'apps.agents.tasks.run_sentiment_agent',
        'schedule': crontab(minute='0', day_of_week='1-5'),
    },

    # ─── Every 2 Hours (Market Hours: Mon-Fri) ────────────────────────────────
    'fetch_social_data_every_2h': {
        'task': 'apps.data_ingestion.tasks.fetch_social_data',
        'schedule': crontab(minute='0', hour='*/2', day_of_week='1-5'),
    },

    # ─── Daily at 6:00 PM IST (After Market Mon-Fri) ──────────────────────────
    'fetch_fundamental_data_daily': {
        'task': 'apps.data_ingestion.tasks.fetch_fundamental_data',
        'schedule': crontab(minute='0', hour='18', day_of_week='1-5'),
    },
    'fetch_macro_data_daily': {
        'task': 'apps.data_ingestion.tasks.fetch_macro_data',
        'schedule': crontab(minute='0', hour='18', day_of_week='1-5'),
    },
    'run_fundamental_agent_daily': {
        'task': 'apps.agents.tasks.run_fundamental_agent',
        'schedule': crontab(minute='0', hour='18', day_of_week='1-5'),
    },

    # ─── Daily at Midnight (Every Day) ────────────────────────────────────────
    'purge_stale_data_daily': {
        'task': 'apps.portfolio.tasks.purge_stale_data',
        'schedule': crontab(minute='0', hour='0'),
    },
}

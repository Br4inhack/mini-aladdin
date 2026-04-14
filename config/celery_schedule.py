from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {

    # ── Person 2 — Data Ingestion ──────────────────────────────────────
    'ingest-price-history-daily': {
        'task': 'apps.data_ingestion.tasks.ingest_watchlist_price_history',
        'schedule': crontab(hour=18, minute=30),  # after NSE close 3:30 PM IST
    },
    'ingest-price-history-batch-weekly': {
        'task': 'apps.data_ingestion.tasks.ingest_watchlist_price_history_batch',
        'schedule': crontab(day_of_week=0, hour=6, minute=0),  # Sunday 6 AM backfill
    },
    'ingest-benchmark-daily': {
        'task': 'apps.data_ingestion.tasks.ingest_benchmark_history',
        'schedule': crontab(hour=19, minute=0),
    },
    'ingest-nse-bhavcopy-daily': {
        'task': 'apps.data_ingestion.tasks.ingest_nse_bhavcopy_prices',
        'schedule': crontab(hour=19, minute=30),
        'kwargs': {'trade_date': ''},  # filled dynamically — Person 2 handles this
    },
    'ingest-fred-macro-weekly': {
        'task': 'apps.data_ingestion.tasks.ingest_fred_macro_indicator',
        'schedule': crontab(day_of_week=1, hour=7, minute=0),  # Monday 7 AM
        'kwargs': {'indicator_name': 'US_GDP', 'fred_code': 'GDP'},
    },
    'ingest-rbi-macro-weekly': {
        'task': 'apps.data_ingestion.tasks.ingest_rbi_macro_data',
        'schedule': crontab(day_of_week=1, hour=7, minute=30),
    },
    'data-quality-check-daily': {
        'task': 'apps.data_ingestion.tasks.run_data_quality_checks',
        'schedule': crontab(hour=20, minute=0),
    },

    # ── Person 3 — Feature Engine + Market Risk Agent ──────────────────
    # Person 3 fills in their actual task names here when they merge
    # 'run-feature-engineering-daily': {
    #     'task': 'apps.feature_engine.tasks.run_feature_engineering',
    #     'schedule': crontab(hour=20, minute=30),
    # },

    # ── Person 4 — Sentiment + Decision Agent ─────────────────────────
    # Person 4 fills in their actual task names here when they merge
    # 'run-sentiment-pipeline-daily': {
    #     'task': 'apps.decision_engine.tasks.run_sentiment_pipeline',
    #     'schedule': crontab(hour=21, minute=0),
    # },

    # ── Person 1 — Portfolio State Engine ─────────────────────────────
    'update-portfolio-state-every-15min': {
        'task': 'apps.portfolio.tasks.update_portfolio_state',
        'schedule': crontab(minute='*/15'),  # every 15 minutes during market hours
    },
    'run-alert-engine-every-15min': {
        'task': 'apps.portfolio.tasks.run_alert_engine_task',
        'schedule': crontab(minute='*/15'),
        'kwargs': {'portfolio_id': 1},
    },
}

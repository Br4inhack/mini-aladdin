from django.urls import path
from . import views

app_name = 'data_ingestion'

urlpatterns = [
    # ── Health & Coverage ───────────────────────────────────────────────────
    path('health/', views.health, name='health'),
    path('coverage/', views.watchlist_coverage, name='coverage'),

    # ── Ingestion Logs ──────────────────────────────────────────────────────
    path('logs/', views.ingestion_log_list, name='log-list'),
    path('logs/summary/', views.ingestion_log_summary, name='log-summary'),

    # ── Trigger Endpoints ───────────────────────────────────────────────────
    path('trigger/prices/', views.trigger_price_ingestion, name='trigger-prices'),
    path('trigger/prices/ticker/', views.trigger_ticker_price_ingestion, name='trigger-ticker-price'),
    path('trigger/fundamentals/', views.trigger_fundamentals_ingestion, name='trigger-fundamentals'),
    path('trigger/macro/', views.trigger_macro_ingestion, name='trigger-macro'),
    path('trigger/fred/', views.trigger_fred_ingestion, name='trigger-fred'),
    path('trigger/bhavcopy/', views.trigger_bhavcopy_ingestion, name='trigger-bhavcopy'),

    # ── Data Quality ────────────────────────────────────────────────────────
    path('quality/', views.data_quality_report, name='quality-report'),
    path('quality/trigger/', views.trigger_quality_check, name='quality-trigger'),

    # ── Data Read Endpoints ──────────────────────────────────────────────────
    path('prices/', views.price_history, name='price-history'),
    path('fundamentals/', views.fundamental_data, name='fundamental-data'),
    path('macro/', views.macro_indicators, name='macro-indicators'),
    path('fii-dii/', views.fii_dii_data, name='fii-dii'),
]

"""
Root URL configuration for the mini-aladdin CRPMS project.

URL patterns:
  /admin/       — Django admin panel
  /api/         — Django REST Framework API routes (namespaced per app)
  /dashboard/   — Dashboard app views
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Django admin
    path('admin/', admin.site.urls),

    # REST API — each app will provide its own router in apps/<app>/urls.py
    path('api/portfolio/', include('apps.portfolio.urls', namespace='portfolio')),
    path('api/agents/', include('apps.agents.urls', namespace='agents')),
    path('api/data/', include('apps.data_ingestion.urls', namespace='data_ingestion')),
    path('api/features/', include('apps.feature_engine.urls', namespace='feature_engine')),
    path('api/decisions/', include('apps.decision_engine.urls', namespace='decision_engine')),
    path('api/backtest/', include('apps.backtester.urls', namespace='backtester')),

    # Dashboard web UI
    path('dashboard/', include('apps.dashboard.urls', namespace='dashboard')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

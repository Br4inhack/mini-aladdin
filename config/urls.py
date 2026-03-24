"""
Main URL Configuration for the mini-aladdin CRPMS project.
Routes traffic to the Django admin, DRF APIs, and the frontend Dashboard.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Built-in Django Admin Interface
    path('admin/', admin.site.urls),
    
    # CRPMS REST API Layer
    path('api/', include('apps.portfolio.urls')),
    
    # CRPMS Frontend Dashboard
    path('', include('apps.dashboard.urls')),
]

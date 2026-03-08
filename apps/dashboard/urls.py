"""
URL routing for the Frontend Dashboard.
"""
from django.urls import path
from apps.dashboard import views

urlpatterns = [
    path('', views.DashboardHomeView.as_view(), name='dashboard-home'),
]

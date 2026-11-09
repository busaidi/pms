from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    path("search/", views.global_search, name="global_search"),
    path("dashboard/rent/", views.rent_dashboard, name="rent_dashboard"),
    path("dashboard/financial/", views.financial_dashboard, name="financial_dashboard"),
]

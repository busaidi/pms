from django.urls import path
from . import views

urlpatterns = [
    path("", views.application_list, name="application_list"),
    path("<int:application_id>/", views.application_workspace, name="application_workspace"),
    path("<int:application_id>/transition/", views.application_transition, name="application_transition"),
    path("<int:application_id>/convert/", views.application_convert, name="application_convert"),
]

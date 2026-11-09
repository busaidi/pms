from django.urls import path

from . import views

urlpatterns = [
    path("", views.listing_index, name="listing_index"),
    path("media/<int:media_id>/", views.public_media, name="public_listing_media"),
    path("<slug:slug>/unit-types/<slug:unit_type_slug>/", views.unit_type_detail, name="listing_unit_type"),
    path("<slug:slug>/", views.listing_detail, name="listing_detail"),
    path("<slug:slug>/apply/", views.apply, name="listing_apply"),
]

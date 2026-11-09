from django.urls import path
from . import leasing_views as views

urlpatterns = [
    path("tenants/", views.tenant_list, name="tenant_list"),
    path("tenants/new/", views.tenant_create, name="tenant_create"),
    path("tenants/<int:tenant_id>/", views.tenant_workspace, name="tenant_workspace"),
    path("tenants/<int:tenant_id>/edit/", views.tenant_edit, name="tenant_edit"),
    path("tenants/<int:tenant_id>/archive/", views.tenant_archive, name="tenant_archive"),
    path("tenants/<int:tenant_id>/restore/", views.tenant_restore, name="tenant_restore"),
    path("tenants/<int:tenant_id>/invite/", views.tenant_invite, name="tenant_invite"),
    path("tenants/<int:tenant_id>/disable-access/", views.tenant_disable_access, name="tenant_disable_access"),
    path("tenants/<int:tenant_id>/documents/add/", views.tenant_document_add, name="tenant_document_add"),
    path("tenants/<int:tenant_id>/documents/<int:document_id>/", views.tenant_document_download, name="tenant_document_download"),
    path("tenants/<int:tenant_id>/documents/<int:document_id>/delete/", views.tenant_document_delete, name="tenant_document_delete"),
    path("tenant-invite/<str:token>/", views.tenant_invitation_accept, name="tenant_invitation_accept"),
    path("leases/", views.lease_list, name="lease_list"),
    path("leases/new/", views.lease_create, name="lease_create"),
    path("leases/expirations/", views.lease_expirations, name="lease_expirations"),
    path("leases/<int:lease_id>/", views.lease_workspace, name="lease_workspace"),
    path("leases/<int:lease_id>/update/", views.lease_update, name="lease_update"),
    path("leases/<int:lease_id>/terminate/", views.lease_terminate, name="lease_terminate"),
    path("leases/<int:lease_id>/move/", views.lease_move, name="lease_move"),
    path("leases/<int:lease_id>/renew/", views.lease_renew, name="lease_renew"),
    path("leases/<int:lease_id>/move-out/", views.lease_move_out, name="lease_move_out"),
    path("leases/<int:lease_id>/deposit-settlement/", views.lease_deposit_settlement, name="lease_deposit_settlement"),
]

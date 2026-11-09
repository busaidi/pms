from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Tenant, TenantDocument


class TenantIdentityUploadTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = get_user_model().objects.create_superuser("identity-admin", "identity@example.test", "test-password")
        self.client.force_login(self.user)

    def data(self):
        return {"full_name": "Identity test tenant", "phone": "90000111", "id_number": "TEST-IDENTITY", "is_active": "on"}

    def upload(self, name="identity.pdf"):
        return SimpleUploadedFile(name, b"%PDF-1.4\nidentity-test", content_type="application/pdf")

    def test_create_saves_both_identity_documents_under_tenant(self):
        response = self.client.post(reverse("tenant_create"), {**self.data(), "id_card_file": self.upload(), "passport_file": self.upload("passport.pdf")})
        tenant = Tenant.objects.get(id_number="TEST-IDENTITY")
        self.assertRedirects(response, reverse("tenant_workspace", args=(tenant.pk,)))
        self.assertEqual(set(tenant.documents.values_list("document_type", flat=True)), {"id_card", "passport"})
        for document in tenant.documents.all():
            self.assertTrue(document.file.storage.exists(document.file.name))
        self.assertContains(self.client.get(reverse("tenant_workspace", args=(tenant.pk,))), "وثائق الهوية")

    def test_edit_appends_documents_and_preserves_existing_files(self):
        tenant = Tenant.objects.create(**{k: v for k, v in self.data().items() if k != "is_active"})
        original = TenantDocument.objects.create(tenant=tenant, name="Old identity", document_type="id_card", file=self.upload())
        response = self.client.post(reverse("tenant_edit", args=(tenant.pk,)), {**self.data(), "passport_file": self.upload("passport.pdf")})
        self.assertEqual(response.status_code, 302)
        original.refresh_from_db()
        self.assertTrue(original.file.storage.exists(original.file.name))
        self.assertEqual(tenant.documents.count(), 2)
        self.client.post(reverse("tenant_edit", args=(tenant.pk,)), self.data())
        self.assertEqual(tenant.documents.count(), 2)

    def test_invalid_upload_blocks_tenant_and_document_save(self):
        response = self.client.post(reverse("tenant_create"), {**self.data(), "id_card_file": self.upload(), "passport_file": self.upload("passport.exe")})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tenant.objects.filter(id_number="TEST-IDENTITY").exists())
        self.assertEqual(TenantDocument.objects.count(), 0)

    def test_invalid_edit_preserves_tenant_data(self):
        tenant = Tenant.objects.create(full_name="Original", phone="90000111")
        response = self.client.post(reverse("tenant_edit", args=(tenant.pk,)), {**self.data(), "id_card_file": self.upload("bad.exe")})
        self.assertEqual(response.status_code, 200)
        tenant.refresh_from_db()
        self.assertEqual(tenant.full_name, "Original")
        self.assertEqual(tenant.documents.count(), 0)

    def test_other_user_cannot_attach_to_tenant(self):
        tenant = Tenant.objects.create(full_name="Protected", phone="90000111", created_by=self.user)
        self.client.force_login(get_user_model().objects.create_user("identity-denied"))
        self.assertEqual(self.client.post(reverse("tenant_edit", args=(tenant.pk,)), {**self.data(), "id_card_file": self.upload()}).status_code, 404)
        self.assertEqual(tenant.documents.count(), 0)

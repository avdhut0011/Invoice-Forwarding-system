from django.test import TestCase, Client
from django.urls import reverse
from apps.organization.models import LegalEntity, Unit, User, RoleChoices

class PortalViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.legal_entity = LegalEntity.objects.create(name="Ashoka Education Foundation", code="AEF")
        self.unit = Unit.objects.create(name="Ashoka Universal School - Ashoka Marg", code="AUS-AM", legal_entity=self.legal_entity)
        self.user = User.objects.create_user(
            username="testuser",
            password="password123",
            role=RoleChoices.ADMIN,
            primary_unit=self.unit,
            email="admin@test.com"
        )

    def test_unauthenticated_redirect(self):
        response = self.client.get(reverse('portal:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_login_view(self):
        response = self.client.get(reverse('portal:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_authenticated_portal_views(self):
        self.client.login(username="testuser", password="password123")
        
        endpoints = [
            'portal:dashboard',
            'portal:store_portal',
            'portal:purchase_portal',
            'portal:accounts_portal',
        ]
        for name in endpoints:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, f"Failed for {name}")

    def test_purchase_search_po_htmx(self):
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse('portal:purchase_search_po') + '?po_number=PO/2026/00142')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'portal/partials/po_search_results.html')

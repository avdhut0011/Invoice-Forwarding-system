from django.test import TestCase, Client
from django.urls import reverse
from apps.organization.models import LegalEntity, Unit, User, RoleChoices

class ReportsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.legal_entity = LegalEntity.objects.create(name="Ashoka Education Foundation", code="AEF")
        self.unit = Unit.objects.create(name="Ashoka Universal School - Ashoka Marg", code="AUS-AM", legal_entity=self.legal_entity)
        self.user = User.objects.create_user(
            username="testreporter",
            password="password123",
            role=RoleChoices.MANAGER,
            primary_unit=self.unit,
            email="manager@test.com"
        )

    def test_reports_summary_view(self):
        self.client.login(username="testreporter", password="password123")
        response = self.client.get(reverse('reports:summary'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/summary.html')

    def test_export_excel_report(self):
        self.client.login(username="testreporter", password="password123")
        response = self.client.get(reverse('reports:export_excel'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('attachment; filename="FMS_Report_', response['Content-Disposition'])

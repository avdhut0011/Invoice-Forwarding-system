from datetime import date
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status

from apps.organization.models import LegalEntity, Unit, User, RoleChoices
from apps.procurement.models import Supplier, PaymentTerms
from apps.receipts.models import GoodsReceipt, ReceiptStatusChoices
from apps.invoices.models import Invoice, InvoiceStatusChoices
from apps.workflow.models import HandoverBatch, HandoverTypeChoices, ApprovalThreshold

class APITestCaseSuite(APITestCase):
    def setUp(self):
        self.legal_entity = LegalEntity.objects.create(name="Ashoka Education Foundation", code="AEF")
        self.unit = Unit.objects.create(name="Ashoka Universal School - Ashoka Marg", code="AUS-AM", legal_entity=self.legal_entity)
        self.terms = PaymentTerms.objects.create(name="Net 30 Days", credit_days=30)
        self.supplier = Supplier.objects.create(name="Ashoka Stationers", code="SUP-001", payment_terms=self.terms)

        self.store_user = User.objects.create_user(
            username="api_store", password="password123", role=RoleChoices.STORE, primary_unit=self.unit, email="store@test.com"
        )
        self.purchase_user = User.objects.create_user(
            username="api_purchase", password="password123", role=RoleChoices.PURCHASE, primary_unit=self.unit, email="purchase@test.com"
        )
        self.accounts_user = User.objects.create_user(
            username="api_accounts", password="password123", role=RoleChoices.ACCOUNTS, primary_unit=self.unit, email="accounts@test.com"
        )
        self.manager_user = User.objects.create_user(
            username="api_manager", password="password123", role=RoleChoices.MANAGER, primary_unit=self.unit, email="manager@test.com"
        )

        # Multi-Tier Approval Thresholds: Tier 1 applies to all, Tier 2 kicks in at >= 50,000
        ApprovalThreshold.objects.create(
            tier_level=1, name="Tier 1 Accounts", min_amount=Decimal("0.00"),
            required_role="ACCOUNTS", can_self_approve=False
        )
        ApprovalThreshold.objects.create(
            tier_level=2, name="Tier 2 Manager", min_amount=Decimal("50000.00"),
            required_role="MANAGER", can_self_approve=False
        )

    def test_unauthenticated_api_request_rejected(self):
        url = reverse('api:receipt-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_receipt_list_and_create(self):
        self.client.login(username="api_store", password="password123")
        url = reverse('api:receipt-list')

        # List
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Create
        payload = {
            'unit': str(self.unit.id),
            'supplier': self.supplier.name,
            'material_date': '2026-10-15',
            'doc_type': 'PO',
            'po_wo_number': 'PO-API-101',
            'grn_number': 'GRN-API-101',
            'grn_date': '2026-10-15',
            'description': 'Test material through API',
            'quantity': '5.000',
            'unit_price': '100.00'
        }
        res_create = self.client.post(url, data=payload)
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res_create.data['st_number'].startswith('ST-'))

    def test_api_multi_tier_approval_flow(self):
        # Create an invoice of ₹75,000 requiring both Tier 1 (Accounts) and Tier 2 (Manager)
        inv = Invoice.objects.create(
            bill_unique_id="BILL-API-99",
            unit=self.unit,
            supplier=self.supplier,
            supplier_name_raw=self.supplier.name,
            invoice_number="INV-API-99",
            invoice_date=date(2026, 10, 16),
            gross_amount=Decimal('75000.00'),
            net_amount=Decimal('75000.00'),
            submitted_by=self.purchase_user,
            status=InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS
        )

        approve_url = reverse('api:invoice-approve', kwargs={'pk': inv.id})

        # 1. Accounts user approves Tier 1
        self.client.login(username="api_accounts", password="password123")
        res1 = self.client.post(approve_url, {'comments': 'Tier 1 Accounts verified'})
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatusChoices.APPROVAL_PENDING) # Still pending Tier 2

        # 2. Manager approves Tier 2 (Final sign-off)
        self.client.login(username="api_manager", password="password123")
        res2 = self.client.post(approve_url, {'comments': 'Tier 2 Manager approved'})
        self.assertEqual(res2.status_code, status.HTTP_200_OK)

        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatusChoices.APPROVED) # Fully approved!

    def test_api_self_approval_prevention(self):
        # Submitter attempts to self-approve
        inv = Invoice.objects.create(
            bill_unique_id="BILL-SELF-01",
            unit=self.unit,
            supplier=self.supplier,
            supplier_name_raw=self.supplier.name,
            invoice_number="INV-SELF-01",
            invoice_date=date(2026, 10, 16),
            gross_amount=Decimal('20000.00'),
            net_amount=Decimal('20000.00'),
            submitted_by=self.accounts_user, # accounts user submitted it
            status=InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS
        )
        approve_url = reverse('api:invoice-approve', kwargs={'pk': inv.id})
        self.client.login(username="api_accounts", password="password123")
        
        res = self.client.post(approve_url, {'comments': 'Self approval attempt'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Self-approval is prohibited", res.data['error'])

    def test_api_return_for_correction(self):
        inv = Invoice.objects.create(
            bill_unique_id="BILL-RET-01",
            unit=self.unit,
            supplier=self.supplier,
            supplier_name_raw=self.supplier.name,
            invoice_number="INV-RET-01",
            invoice_date=date(2026, 10, 16),
            gross_amount=Decimal('15000.00'),
            net_amount=Decimal('15000.00'),
            submitted_by=self.purchase_user,
            status=InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS
        )
        return_url = reverse('api:invoice-return-for-correction', kwargs={'pk': inv.id})
        self.client.login(username="api_accounts", password="password123")

        res = self.client.post(return_url, {'reason': 'Supplier GST number missing on bill'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatusChoices.RETURNED_FOR_CORRECTION)

    def test_api_custody_acknowledgment(self):
        batch = HandoverBatch.objects.create(
            batch_number="HB-API-01",
            handover_type=HandoverTypeChoices.STORE_TO_PURCHASE,
            unit=self.unit,
            sender=self.store_user,
            intended_recipient=self.purchase_user,
            checklist_summary="1 packet"
        )
        ack_url = reverse('api:handover-acknowledge', kwargs={'pk': batch.id})
        self.client.login(username="api_purchase", password="password123")

        res = self.client.post(ack_url, {'all_documents_present': True, 'remarks': 'All verified'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        batch.refresh_from_db()
        self.assertTrue(batch.is_acknowledged)

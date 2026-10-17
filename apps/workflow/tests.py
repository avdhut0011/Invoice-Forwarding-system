from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from apps.organization.models import LegalEntity, Unit, User, RoleChoices
from apps.procurement.models import Supplier, PaymentTerms
from apps.receipts.models import GoodsReceipt, ReceiptStatusChoices
from apps.invoices.models import Invoice, InvoiceStatusChoices
from apps.workflow.models import HandoverBatch, HandoverTypeChoices, WorkflowTask, TaskStatusChoices
from apps.workflow.services import (
    submit_store_receipt, create_handover_batch, acknowledge_custody,
    approve_invoice, return_invoice_for_correction
)
from apps.invoices.services import allocate_and_submit_invoice, submit_na_invoice

class WorkflowServiceTestCase(TestCase):
    def setUp(self):
        self.legal_entity = LegalEntity.objects.create(name="Ashoka Education Foundation", code="AEF")
        self.unit = Unit.objects.create(name="Ashoka Universal School - Ashoka Marg", code="AUS-AM", legal_entity=self.legal_entity)
        self.terms = PaymentTerms.objects.create(name="Net 30 Days", credit_days=30)
        self.supplier = Supplier.objects.create(name="Ashoka Stationers", code="SUP-001", payment_terms=self.terms)

        self.store_user = User.objects.create_user(
            username="test_store", role=RoleChoices.STORE, primary_unit=self.unit, email="store@test.com"
        )
        self.purchase_user = User.objects.create_user(
            username="test_purchase", role=RoleChoices.PURCHASE, primary_unit=self.unit, email="purchase@test.com"
        )
        self.accounts_user = User.objects.create_user(
            username="test_accounts", role=RoleChoices.ACCOUNTS, primary_unit=self.unit, email="accounts@test.com"
        )

    def test_submit_store_receipt(self):
        data = {
            'unit_id': str(self.unit.id),
            'material_date': date(2026, 10, 15),
            'supplier': self.supplier.name,
            'doc_type': 'PO',
            'po_wo_number': 'PO-991',
            'grn_number': 'GRN-1001',
            'grn_date': date(2026, 10, 15),
            'description': 'Test materials',
            'quantity': '10.000',
            'unit_price': '500.00'
        }
        receipt = submit_store_receipt(user=self.store_user, data=data)
        
        self.assertTrue(receipt.st_number.startswith('ST-'))
        self.assertEqual(receipt.status, ReceiptStatusChoices.PENDING_HANDOVER)
        self.assertEqual(receipt.lines.count(), 1)
        self.assertEqual(receipt.lines.first().received_quantity, Decimal('10.000'))

    def test_handover_and_custody_acknowledgment(self):
        data = {
            'unit_id': str(self.unit.id),
            'material_date': date(2026, 10, 15),
            'supplier': self.supplier.name,
            'grn_number': 'GRN-1002',
            'grn_date': date(2026, 10, 15),
            'description': 'Test custody flow'
        }
        receipt = submit_store_receipt(user=self.store_user, data=data)

        # 1. Dispatch Handover Batch
        batch = create_handover_batch(
            sender=self.store_user,
            handover_type=HandoverTypeChoices.STORE_TO_PURCHASE,
            unit=self.unit,
            intended_recipient=self.purchase_user,
            item_ids=[receipt.id],
            checklist_summary="1 GRN attached"
        )
        self.assertTrue(batch.batch_number.startswith('HB-'))
        self.assertFalse(batch.is_acknowledged)
        
        # Verify open workflow task created
        task = WorkflowTask.objects.get(handover_batch=batch)
        self.assertEqual(task.status, TaskStatusChoices.OPEN)
        self.assertEqual(task.assigned_to, self.purchase_user)

        # 2. Acknowledge Custody
        batch = acknowledge_custody(user=self.purchase_user, batch_id=batch.id)
        self.assertTrue(batch.is_acknowledged)
        
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, ReceiptStatusChoices.CUSTODY_ACKNOWLEDGED)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatusChoices.COMPLETED)

    def test_invoice_allocation_success(self):
        # Create two receipts
        r1 = submit_store_receipt(user=self.store_user, data={
            'unit_id': str(self.unit.id), 'material_date': date(2026, 10, 15), 'supplier': self.supplier.name,
            'grn_number': 'GRN-A', 'grn_date': date(2026, 10, 15), 'description': 'Item A'
        })
        r2 = submit_store_receipt(user=self.store_user, data={
            'unit_id': str(self.unit.id), 'material_date': date(2026, 10, 15), 'supplier': self.supplier.name,
            'grn_number': 'GRN-B', 'grn_date': date(2026, 10, 15), 'description': 'Item B'
        })

        invoice_data = {
            'unit_id': str(self.unit.id),
            'supplier_name': self.supplier.name,
            'invoice_number': 'INV-TEST-001',
            'invoice_date': date(2026, 10, 16),
            'gross_amount': Decimal('100000.00'),
            'due_date': date(2026, 11, 15),
        }
        allocations_data = [
            {'receipt_id': str(r1.id), 'allocated_amount': Decimal('60000.00')},
            {'receipt_id': str(r2.id), 'allocated_amount': Decimal('40000.00')},
        ]

        inv = allocate_and_submit_invoice(
            user=self.purchase_user, invoice_data=invoice_data, allocations_data=allocations_data
        )

        self.assertTrue(inv.bill_unique_id.startswith('BILL-'))
        self.assertEqual(inv.gross_amount, Decimal('100000.00'))
        self.assertEqual(inv.allocations.count(), 2)

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.status, ReceiptStatusChoices.BILL_LINKED)
        self.assertEqual(r2.status, ReceiptStatusChoices.BILL_LINKED)
        self.assertEqual(r1.bill_unique_id, inv.bill_unique_id)
        self.assertEqual(r2.bill_unique_id, inv.bill_unique_id)

    def test_invoice_allocation_amount_mismatch(self):
        r1 = submit_store_receipt(user=self.store_user, data={
            'unit_id': str(self.unit.id), 'material_date': date(2026, 10, 15), 'supplier': self.supplier.name,
            'grn_number': 'GRN-MISMATCH', 'grn_date': date(2026, 10, 15), 'description': 'Item M'
        })
        invoice_data = {
            'unit_id': str(self.unit.id),
            'supplier_name': self.supplier.name,
            'invoice_number': 'INV-ERR-001',
            'invoice_date': date(2026, 10, 16),
            'gross_amount': Decimal('100000.00'),
        }
        # Allocation sums to 50,000 but invoice is 100,000 -> must raise error!
        allocations_data = [
            {'receipt_id': str(r1.id), 'allocated_amount': Decimal('50000.00')},
        ]
        with self.assertRaises(ValueError):
            allocate_and_submit_invoice(
                user=self.purchase_user, invoice_data=invoice_data, allocations_data=allocations_data
            )

    def test_return_for_correction_and_approval(self):
        inv = Invoice.objects.create(
            bill_unique_id="BILL-TEST-88",
            unit=self.unit,
            supplier=self.supplier,
            supplier_name_raw=self.supplier.name,
            invoice_number="INV-88",
            invoice_date=date(2026, 10, 16),
            gross_amount=Decimal('5000.00'),
            net_amount=Decimal('5000.00'),
            submitted_by=self.purchase_user,
            status=InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS
        )

        # 1. Accounts returns for correction
        inv = return_invoice_for_correction(user=self.accounts_user, invoice_id=inv.id, reason="Rate mismatch on item 2")
        self.assertEqual(inv.status, InvoiceStatusChoices.RETURNED_FOR_CORRECTION)
        self.assertEqual(inv.exceptions.count(), 1)
        self.assertEqual(inv.exceptions.first().reason, "Rate mismatch on item 2")

        # 2. Re-submitted & Approved
        inv = approve_invoice(user=self.accounts_user, invoice_id=inv.id, comments="Corrected rate verified")
        self.assertEqual(inv.status, InvoiceStatusChoices.APPROVED)
        self.assertEqual(inv.approval_decisions.count(), 1)

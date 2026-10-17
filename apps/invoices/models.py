import uuid
from django.db import models, transaction
from django.utils import timezone
from apps.organization.models import Unit, User
from apps.procurement.models import Supplier
from apps.receipts.models import GoodsReceipt, ReceiptLine

class InvoiceTypeChoices(models.TextChoices):
    PO_MATCHED = 'PO_MATCHED', 'PO / GRN Matched'
    NON_PO = 'NON_PO', 'Non-PO / Direct Expense'
    SERVICE = 'SERVICE', 'Service Invoice'
    ADVANCE = 'ADVANCE', 'Advance / Proforma'

class InvoiceStatusChoices(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    SUBMITTED_TO_ACCOUNTS = 'SUBMITTED_TO_ACCOUNTS', 'Submitted to Accounts'
    CUSTODY_ACKNOWLEDGED = 'CUSTODY_ACKNOWLEDGED', 'Custody Acknowledged by Accounts'
    UNDER_VERIFICATION = 'UNDER_VERIFICATION', 'Under Verification'
    APPROVAL_PENDING = 'APPROVAL_PENDING', 'Approval Pending'
    APPROVED = 'APPROVED', 'Approved'
    RETURNED_FOR_CORRECTION = 'RETURNED_FOR_CORRECTION', 'Returned for Correction'
    ACCOUNTING_POSTED = 'ACCOUNTING_POSTED', 'Accounting Posted'
    CANCELLED = 'CANCELLED', 'Cancelled'

class BillSequence(models.Model):
    """Sequence tracker for BILL-XXXXX and NA-XXXXX identifiers."""
    prefix = models.CharField(max_length=10, unique=True)
    last_number = models.PositiveIntegerField(default=0)

    @classmethod
    def get_next(cls, prefix='BILL'):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(prefix=prefix)
            seq.last_number += 1
            seq.save()
            return f"{prefix}-{seq.last_number:05d}"

class Invoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bill_unique_id = models.CharField(max_length=50, unique=True, db_index=True)
    na_unique_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    invoice_type = models.CharField(max_length=30, choices=InvoiceTypeChoices.choices, default=InvoiceTypeChoices.PO_MATCHED)
    
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='invoices')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    supplier_name_raw = models.CharField(max_length=255)
    supplier_code = models.CharField(max_length=100, blank=True, null=True)
    
    invoice_number = models.CharField(max_length=100, db_index=True)
    invoice_date = models.DateField()
    gross_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2)
    
    due_date = models.DateField(blank=True, null=True)
    payment_category = models.CharField(max_length=50, default='Credit')
    grn_received_from_stores_on = models.DateField(blank=True, null=True)
    purchase_remark = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=30, choices=InvoiceStatusChoices.choices, default=InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS, db_index=True)
    version = models.PositiveIntegerField(default=1, help_text="Optimistic concurrency version")

    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='submitted_invoices')
    purchase_person_raw = models.CharField(max_length=100, blank=True, null=True)
    submitter_email = models.EmailField(blank=True, null=True)

    bill_scan = models.FileField(upload_to='invoice_scans/%Y/%m/', blank=True, null=True)
    legacy_file_url = models.URLField(max_length=500, blank=True, null=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['unit', 'invoice_number']),
            models.Index(fields=['status']),
            models.Index(fields=['due_date']),
        ]

    def __str__(self):
        return f"{self.bill_unique_id} - Inv: {self.invoice_number} ({self.supplier_name_raw}) ₹{self.gross_amount}"

    def save(self, *args, **kwargs):
        if not self.bill_unique_id:
            self.bill_unique_id = BillSequence.get_next('BILL')
        if not self.net_amount and self.gross_amount is not None:
            self.net_amount = self.gross_amount
        super().save(*args, **kwargs)

class InvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    line_number = models.PositiveIntegerField(default=1)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1.000)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)

    class Meta:
        ordering = ['line_number']

class InvoiceAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='allocations')
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name='allocations')
    receipt_line = models.ForeignKey(ReceiptLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='allocations')
    allocated_amount = models.DecimalField(max_digits=14, decimal_places=2)
    allocated_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1.000)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('invoice', 'goods_receipt', 'receipt_line')

    def __str__(self):
        return f"Alloc: {self.invoice.bill_unique_id} -> {self.goods_receipt.st_number} (₹{self.allocated_amount})"

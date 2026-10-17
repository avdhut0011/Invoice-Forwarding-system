import uuid
from django.db import models, transaction
from django.utils import timezone
from apps.organization.models import Unit, User
from apps.procurement.models import Supplier, PurchaseOrder, OrderLine

class DocTypeChoices(models.TextChoices):
    PO = 'PO', 'PO (Purchase Order)'
    WO = 'WO', 'WO (Work Order)'
    INVOICE = 'INVOICE', 'Invoice Number'
    DC = 'DC', 'DC (Delivery Challan)'

class PaymentCategoryChoices(models.TextChoices):
    CREDIT = 'Credit', 'Credit'
    CASH = 'Cash', 'Cash'
    IOU = 'IOU', 'IOU'
    ONLINE = 'Online', 'Online'

class ReceiptStatusChoices(models.TextChoices):
    PENDING_HANDOVER = 'PENDING_HANDOVER', 'Pending Handover'
    HANDED_OVER = 'HANDED_OVER', 'Handed Over to Purchase'
    CUSTODY_ACKNOWLEDGED = 'CUSTODY_ACKNOWLEDGED', 'Custody Acknowledged'
    BILL_LINKED = 'BILL_LINKED', 'Bill Linked'
    DELETED = 'DELETED', 'Deleted'

class GoodsReceiptSequence(models.Model):
    """Sequence tracker for ST-XXXXX identifiers."""
    prefix = models.CharField(max_length=10, default='ST', unique=True)
    last_number = models.PositiveIntegerField(default=0)

    @classmethod
    def get_next(cls, prefix='ST'):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(prefix=prefix)
            seq.last_number += 1
            seq.save()
            return f"{prefix}-{seq.last_number:05d}"

class GoodsReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    st_number = models.CharField(max_length=50, unique=True, db_index=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='goods_receipts')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='goods_receipts')
    supplier_name_raw = models.CharField(max_length=255)
    material_date = models.DateField(help_text="Date material was received at the store")
    doc_type = models.CharField(max_length=20, choices=DocTypeChoices.choices, default=DocTypeChoices.PO)
    po_wo_number = models.CharField(max_length=100, db_index=True, blank=True, null=True)
    dc_number = models.CharField(max_length=100, blank=True, null=True)
    grn_number = models.CharField(max_length=100, db_index=True)
    grn_date = models.DateField()
    description = models.TextField()
    payment_category = models.CharField(max_length=20, choices=PaymentCategoryChoices.choices, default=PaymentCategoryChoices.CREDIT)
    is_invoice_received = models.BooleanField(default=False)
    store_remark = models.TextField(blank=True, null=True)
    
    assigned_purchase_person = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_receipts')
    assigned_purchase_person_raw = models.CharField(max_length=100, blank=True, null=True)
    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='submitted_receipts')
    store_person_raw = models.CharField(max_length=100, blank=True, null=True)
    submitter_email = models.EmailField(blank=True, null=True)

    status = models.CharField(max_length=30, choices=ReceiptStatusChoices.choices, default=ReceiptStatusChoices.PENDING_HANDOVER, db_index=True)
    
    # Files / Scans
    invoice_scan = models.FileField(upload_to='receipt_scans/invoices/%Y/%m/', blank=True, null=True)
    grn_scan = models.FileField(upload_to='receipt_scans/grns/%Y/%m/', blank=True, null=True)
    legacy_file_link = models.URLField(max_length=500, blank=True, null=True)
    legacy_grn_link = models.URLField(max_length=500, blank=True, null=True)

    # Fast references to linked bill
    bill_unique_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['unit', 'grn_number']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.st_number} - GRN: {self.grn_number} ({self.supplier_name_raw})"

    def save(self, *args, **kwargs):
        if not self.st_number:
            self.st_number = GoodsReceiptSequence.get_next('ST')
        super().save(*args, **kwargs)

class ReceiptLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name='lines')
    order_line = models.ForeignKey(OrderLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='receipt_lines')
    item_description = models.TextField()
    received_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1.000)
    accepted_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1.000)
    rejected_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0.000)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    invoiced_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0.000)

    @property
    def remaining_invoicable_quantity(self):
        return max(0, self.accepted_quantity - self.invoiced_quantity)

    def __str__(self):
        return f"{self.goods_receipt.st_number} line: {self.item_description[:30]}"

class ServiceAcceptance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_ref = models.CharField(max_length=100, unique=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    service_description = models.TextField()
    completion_date = models.DateField()
    accepted_by = models.ForeignKey(User, on_delete=models.PROTECT)
    accepted_at = models.DateTimeField(auto_now_add=True)
    approved_amount = models.DecimalField(max_digits=14, decimal_places=2)
    evidence_document = models.FileField(upload_to='service_evidence/%Y/%m/', blank=True, null=True)

    def __str__(self):
        return f"{self.service_ref} - {self.supplier.name}"

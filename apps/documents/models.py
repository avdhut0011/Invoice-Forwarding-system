import uuid
import hashlib
from django.db import models
from django.utils import timezone
from apps.organization.models import User
from apps.receipts.models import GoodsReceipt
from apps.invoices.models import Invoice

class DocCategoryChoices(models.TextChoices):
    INVOICE_SCAN = 'INVOICE_SCAN', 'Invoice Scan'
    GRN_SCAN = 'GRN_SCAN', 'GRN Scanned Copy'
    PO_COPY = 'PO_COPY', 'PO / WO Copy'
    DELIVERY_CHALLAN = 'DELIVERY_CHALLAN', 'Delivery Challan'
    SERVICE_EVIDENCE = 'SERVICE_EVIDENCE', 'Service Evidence'
    OTHER = 'OTHER', 'Other Attachment'

class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=30, choices=DocCategoryChoices.choices, default=DocCategoryChoices.OTHER)
    file = models.FileField(upload_to='vault/%Y/%m/')
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True, null=True)
    checksum = models.CharField(max_length=64, blank=True, null=True, help_text="SHA-256 hash")
    
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if self.file and hasattr(self.file, 'read'):
            # Calculate sha256
            hasher = hashlib.sha256()
            for chunk in self.file.chunks():
                hasher.update(chunk)
            self.checksum = hasher.hexdigest()
            self.file_size = self.file.size
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.category}: {self.file_name}"

class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    actor_username = models.CharField(max_length=150, default='system')
    action = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=100, db_index=True)
    entity_id = models.CharField(max_length=100)
    business_reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    before_state = models.JSONField(blank=True, null=True)
    after_state = models.JSONField(blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {self.actor_username}: {self.action} on {self.business_reference or self.entity_type}"

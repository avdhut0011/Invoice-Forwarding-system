import uuid
from django.db import models, transaction
from django.utils import timezone
from apps.organization.models import Unit, User
from apps.receipts.models import GoodsReceipt
from apps.invoices.models import Invoice

class HandoverTypeChoices(models.TextChoices):
    STORE_TO_PURCHASE = 'STORE_TO_PURCHASE', 'Store to Purchase'
    PURCHASE_TO_ACCOUNTS = 'PURCHASE_TO_ACCOUNTS', 'Purchase to Accounts'

class HandoverBatchSequence(models.Model):
    prefix = models.CharField(max_length=10, default='HB', unique=True)
    last_number = models.PositiveIntegerField(default=0)

    @classmethod
    def get_next(cls, prefix='HB'):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(prefix=prefix)
            seq.last_number += 1
            seq.save()
            return f"{prefix}-{seq.last_number:05d}"

class HandoverBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_number = models.CharField(max_length=50, unique=True, db_index=True)
    handover_type = models.CharField(max_length=30, choices=HandoverTypeChoices.choices)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='handover_batches')
    
    sender = models.ForeignKey(User, on_delete=models.PROTECT, related_name='dispatched_handovers')
    sender_name_raw = models.CharField(max_length=100, blank=True, null=True)
    
    intended_recipient = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='incoming_handovers')
    intended_recipient_name_raw = models.CharField(max_length=100, blank=True, null=True)
    
    actual_recipient = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_handovers')
    dispatched_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(blank=True, null=True)
    
    is_acknowledged = models.BooleanField(default=False)
    is_incomplete = models.BooleanField(default=False)
    checklist_summary = models.TextField(blank=True, null=True)
    incomplete_notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-dispatched_at']

    def __str__(self):
        return f"{self.batch_number} ({self.get_handover_type_display()}) - {'ACK' if self.is_acknowledged else 'PENDING'}"

    def save(self, *args, **kwargs):
        if not self.batch_number:
            self.batch_number = HandoverBatchSequence.get_next('HB')
        super().save(*args, **kwargs)

class HandoverItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(HandoverBatch, on_delete=models.CASCADE, related_name='items')
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.SET_NULL, null=True, blank=True, related_name='handover_items')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='handover_items')
    is_received = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True, null=True)

class CustodyAcknowledgment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(HandoverBatch, on_delete=models.CASCADE, related_name='acknowledgments')
    acknowledged_by = models.ForeignKey(User, on_delete=models.PROTECT)
    acknowledged_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    all_documents_present = models.BooleanField(default=True)
    remarks = models.TextField(blank=True, null=True)

class TaskTypeChoices(models.TextChoices):
    CUSTODY_ACK = 'CUSTODY_ACK', 'Acknowledge Custody'
    INVOICE_MATCH = 'INVOICE_MATCH', 'Match & Allocate Invoice'
    VERIFICATION = 'VERIFICATION', 'Verify Invoice & Evidence'
    CORRECTION = 'CORRECTION', 'Return Correction Required'
    APPROVAL = 'APPROVAL', 'Approve Invoice'

class TaskStatusChoices(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'

class WorkflowTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_type = models.CharField(max_length=30, choices=TaskTypeChoices.choices)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    assigned_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='workflow_tasks')
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    handover_batch = models.ForeignKey(HandoverBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    deadline = models.DateTimeField()
    status = models.CharField(max_length=20, choices=TaskStatusChoices.choices, default=TaskStatusChoices.OPEN, db_index=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['deadline']

    @property
    def is_overdue(self):
        return self.status == TaskStatusChoices.OPEN and timezone.now() > self.deadline

class ExceptionCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='exceptions', null=True, blank=True)
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name='exceptions', null=True, blank=True)
    reason = models.TextField()
    raised_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='raised_exceptions')
    assigned_owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='assigned_exceptions')
    is_resolved = models.BooleanField(default=False)
    resolution_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(blank=True, null=True)

class ApprovalDecisionChoices(models.TextChoices):
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    RETURNED = 'RETURNED', 'Returned for Correction'

class ApprovalDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='approval_decisions')
    approver = models.ForeignKey(User, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20, choices=ApprovalDecisionChoices.choices)
    comments = models.TextField(blank=True, null=True)
    decided_at = models.DateTimeField(default=timezone.now)

class ApprovalThreshold(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, null=True, blank=True, related_name='approval_thresholds')
    min_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    required_role = models.CharField(max_length=20, default='ACCOUNTS')
    tier_level = models.PositiveIntegerField(default=1)
    can_self_approve = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tier_level', 'min_amount']

    def __str__(self):
        max_str = f"₹{self.max_amount}" if self.max_amount else "No Limit"
        unit_str = f" ({self.unit.name})" if self.unit else " (Global)"
        return f"Tier {self.tier_level}: {self.name} [₹{self.min_amount} - {max_str}] -> {self.required_role}{unit_str}"

class StepStatusChoices(models.TextChoices):
    PENDING = 'PENDING', 'Pending Approval'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    RETURNED = 'RETURNED', 'Returned'
    SKIPPED = 'SKIPPED', 'Skipped'

class InvoiceApprovalStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='approval_steps')
    threshold = models.ForeignKey(ApprovalThreshold, on_delete=models.SET_NULL, null=True, blank=True)
    tier_level = models.PositiveIntegerField(default=1)
    required_role = models.CharField(max_length=20, default='ACCOUNTS')
    status = models.CharField(max_length=20, choices=StepStatusChoices.choices, default=StepStatusChoices.PENDING, db_index=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_approval_steps')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='completed_approval_steps')
    comments = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['tier_level']

    def __str__(self):
        return f"{self.invoice.bill_unique_id} - Tier {self.tier_level} ({self.required_role}): {self.status}"


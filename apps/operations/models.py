import uuid
from django.db import models
from django.utils import timezone

class OutboxStatusChoices(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    DELIVERED = 'DELIVERED', 'Delivered'
    FAILED = 'FAILED', 'Failed'

class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=100, db_index=True)
    recipient_email = models.EmailField(blank=True, null=True)
    recipient_name = models.CharField(max_length=255, blank=True, null=True)
    subject = models.CharField(max_length=255)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=OutboxStatusChoices.choices, default=OutboxStatusChoices.PENDING, db_index=True)
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    delivered_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"[{self.status}] {self.event_type} to {self.recipient_email}"

class DeliveryAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    outbox_event = models.ForeignKey(OutboxEvent, on_delete=models.CASCADE, related_name='delivery_attempts')
    attempt_number = models.PositiveIntegerField()
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, null=True)
    attempted_at = models.DateTimeField(default=timezone.now)

class IdempotencyRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)
    request_path = models.CharField(max_length=255)
    user_id = models.CharField(max_length=100, blank=True, null=True)
    response_code = models.PositiveIntegerField(default=200)
    response_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.idempotency_key} ({self.response_code})"

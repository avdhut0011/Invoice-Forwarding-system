import uuid
from django.db import models
from apps.organization.models import Unit, User

class PaymentTerms(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    credit_days = models.PositiveIntegerField(default=30)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.credit_days} days)"

class Supplier(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, db_index=True)
    code = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    gstin = models.CharField(max_length=20, blank=True, null=True)
    payment_terms = models.ForeignKey(PaymentTerms, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name

class POStatusChoices(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    APPROVED = 'APPROVED', 'Approved'
    PARTIALLY_RECEIVED = 'PARTIALLY_RECEIVED', 'Partially Received'
    FULLY_RECEIVED = 'FULLY_RECEIVED', 'Fully Received'
    CANCELLED = 'CANCELLED', 'Cancelled'

class PurchaseOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po_number = models.CharField(max_length=100, db_index=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='purchase_orders')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    order_date = models.DateField()
    status = models.CharField(max_length=30, choices=POStatusChoices.choices, default=POStatusChoices.APPROVED)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('unit', 'po_number')

    def __str__(self):
        return f"PO: {self.po_number} ({self.supplier.name})"

class OrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    line_number = models.PositiveIntegerField(default=1)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_of_measure = models.CharField(max_length=50, default='NOS')
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    received_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0.000)
    invoiced_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0.000)

    class Meta:
        ordering = ['line_number']

    def __str__(self):
        return f"{self.purchase_order.po_number} - Line {self.line_number}: {self.description[:30]}"

from rest_framework import serializers
from apps.organization.models import Unit, User
from apps.procurement.models import Supplier, PaymentTerms
from apps.receipts.models import GoodsReceipt, ReceiptLine
from apps.invoices.models import Invoice, InvoiceAllocation, InvoiceLine
from apps.workflow.models import (
    HandoverBatch, HandoverItem, CustodyAcknowledgment,
    WorkflowTask, ApprovalThreshold, InvoiceApprovalStep, ApprovalDecision
)
from apps.documents.models import AuditEvent

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ['id', 'name', 'code', 'location', 'is_active']

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'role', 'phone', 'department']

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ['id', 'name', 'code', 'contact_person', 'email', 'phone', 'gstin', 'is_active']

class ReceiptLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptLine
        fields = ['id', 'item_description', 'received_quantity', 'accepted_quantity', 'rejected_quantity', 'invoiced_quantity', 'unit_price', 'remaining_invoicable_quantity']

class GoodsReceiptSerializer(serializers.ModelSerializer):
    lines = ReceiptLineSerializer(many=True, read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)

    class Meta:
        model = GoodsReceipt
        fields = [
            'id', 'st_number', 'unit', 'unit_name', 'supplier', 'supplier_name_raw',
            'material_date', 'doc_type', 'po_wo_number', 'dc_number', 'grn_number',
            'grn_date', 'description', 'payment_category', 'is_invoice_received',
            'store_remark', 'assigned_purchase_person', 'assigned_purchase_person_raw',
            'submitted_by', 'store_person_raw', 'submitter_email', 'status',
            'bill_unique_id', 'created_at', 'updated_at', 'lines'
        ]
        read_only_fields = ['st_number', 'submitted_by', 'status', 'bill_unique_id', 'created_at', 'updated_at']

class InvoiceAllocationSerializer(serializers.ModelSerializer):
    st_number = serializers.CharField(source='goods_receipt.st_number', read_only=True)
    grn_number = serializers.CharField(source='goods_receipt.grn_number', read_only=True)

    class Meta:
        model = InvoiceAllocation
        fields = ['id', 'goods_receipt', 'st_number', 'grn_number', 'allocated_amount', 'allocated_quantity', 'notes', 'created_at']

class InvoiceApprovalStepSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)

    class Meta:
        model = InvoiceApprovalStep
        fields = ['id', 'tier_level', 'required_role', 'status', 'approved_by', 'approved_by_name', 'comments', 'decided_at']

class InvoiceSerializer(serializers.ModelSerializer):
    allocations = InvoiceAllocationSerializer(many=True, read_only=True)
    approval_steps = InvoiceApprovalStepSerializer(many=True, read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'bill_unique_id', 'na_unique_id', 'invoice_type', 'unit', 'unit_name',
            'supplier', 'supplier_name_raw', 'supplier_code', 'invoice_number',
            'invoice_date', 'gross_amount', 'tax_amount', 'net_amount', 'due_date',
            'payment_category', 'grn_received_from_stores_on', 'purchase_remark',
            'status', 'version', 'submitted_by', 'purchase_person_raw', 'submitter_email',
            'created_at', 'updated_at', 'allocations', 'approval_steps'
        ]
        read_only_fields = ['bill_unique_id', 'na_unique_id', 'submitted_by', 'status', 'version', 'created_at', 'updated_at']

class HandoverItemSerializer(serializers.ModelSerializer):
    st_number = serializers.CharField(source='goods_receipt.st_number', read_only=True)
    bill_unique_id = serializers.CharField(source='invoice.bill_unique_id', read_only=True)

    class Meta:
        model = HandoverItem
        fields = ['id', 'goods_receipt', 'st_number', 'invoice', 'bill_unique_id', 'is_received', 'notes']

class HandoverBatchSerializer(serializers.ModelSerializer):
    items = HandoverItemSerializer(many=True, read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)

    class Meta:
        model = HandoverBatch
        fields = [
            'id', 'batch_number', 'handover_type', 'unit', 'unit_name', 'sender',
            'sender_name_raw', 'intended_recipient', 'intended_recipient_name_raw',
            'actual_recipient', 'dispatched_at', 'acknowledged_at', 'is_acknowledged',
            'is_incomplete', 'checklist_summary', 'incomplete_notes', 'items'
        ]
        read_only_fields = ['batch_number', 'sender', 'actual_recipient', 'dispatched_at', 'acknowledged_at', 'is_acknowledged']

class WorkflowTaskSerializer(serializers.ModelSerializer):
    unit_name = serializers.CharField(source='unit.name', read_only=True)

    class Meta:
        model = WorkflowTask
        fields = [
            'id', 'task_type', 'title', 'description', 'assigned_to', 'unit', 'unit_name',
            'goods_receipt', 'invoice', 'handover_batch', 'deadline', 'status', 'is_overdue',
            'completed_at', 'created_at'
        ]

class ApprovalThresholdSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalThreshold
        fields = ['id', 'name', 'unit', 'min_amount', 'max_amount', 'required_role', 'tier_level', 'can_self_approve', 'is_active']

class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = ['id', 'actor', 'actor_username', 'action', 'entity_type', 'entity_id', 'business_reference', 'before_state', 'after_state', 'reason', 'timestamp']

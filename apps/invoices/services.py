from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from apps.organization.models import Unit, User
from apps.procurement.models import Supplier
from apps.receipts.models import GoodsReceipt, ReceiptStatusChoices
from apps.invoices.models import Invoice, InvoiceLine, InvoiceAllocation, BillSequence, InvoiceTypeChoices, InvoiceStatusChoices
from apps.workflow.models import HandoverBatch, HandoverItem, HandoverTypeChoices, WorkflowTask, TaskTypeChoices, TaskStatusChoices
from apps.documents.models import AuditEvent, Document, DocCategoryChoices
from apps.operations.models import OutboxEvent

@transaction.atomic
def allocate_and_submit_invoice(user, invoice_data, allocations_data, bill_file=None, ip_address=None):
    """
    Submits a supplier bill and allocates it across one or more GoodsReceipts.
    Enforces atomic row-level locks (select_for_update) to prevent concurrent double-allocation.
    """
    receipt_uids = [a['receipt_id'] for a in allocations_data]
    
    # 1. Lock targeted receipt rows
    receipts = list(GoodsReceipt.objects.select_for_update().filter(id__in=receipt_uids))
    if len(receipts) != len(receipt_uids):
        raise ValueError("One or more selected receipts could not be found.")

    # 2. Concurrency & eligibility check
    for r in receipts:
        if r.status in [ReceiptStatusChoices.BILL_LINKED, ReceiptStatusChoices.DELETED]:
            raise ValueError(f"Receipt {r.st_number} is already linked to another bill or deleted. Stale update prevented.")

    gross_amount = Decimal(str(invoice_data.get('gross_amount', '0.00')))
    total_allocated = sum(Decimal(str(a.get('allocated_amount', '0.00'))) for a in allocations_data)
    
    # Enforce allocation sum equals gross invoice amount
    if abs(gross_amount - total_allocated) > Decimal('0.01'):
        raise ValueError(f"Total allocated amount (₹{total_allocated}) must equal the gross bill amount (₹{gross_amount}).")

    unit_id = invoice_data.get('unit_id')
    unit = Unit.objects.get(id=unit_id) if unit_id else receipts[0].unit

    supplier_name = invoice_data.get('supplier_name', receipts[0].supplier_name_raw)
    supplier = Supplier.objects.filter(name__iexact=supplier_name).first() or receipts[0].supplier

    bill_id = BillSequence.get_next('BILL')

    # 3. Create Invoice
    invoice = Invoice.objects.create(
        bill_unique_id=bill_id,
        invoice_type=InvoiceTypeChoices.PO_MATCHED,
        unit=unit,
        supplier=supplier,
        supplier_name_raw=supplier_name,
        supplier_code=invoice_data.get('supplier_code', getattr(supplier, 'code', '') or ''),
        invoice_number=invoice_data.get('invoice_number', '').strip(),
        invoice_date=invoice_data.get('invoice_date'),
        gross_amount=gross_amount,
        tax_amount=Decimal(str(invoice_data.get('tax_amount', '0.00'))),
        net_amount=gross_amount,
        due_date=invoice_data.get('due_date'),
        payment_category=invoice_data.get('payment_category', 'Credit'),
        grn_received_from_stores_on=invoice_data.get('grn_received_from_stores_on', timezone.now().date()),
        purchase_remark=invoice_data.get('purchase_remark', ''),
        status=InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS,
        submitted_by=user,
        purchase_person_raw=user.get_full_name() or user.username,
        submitter_email=user.email,
        bill_scan=bill_file
    )

    # 4. Attach scan to Document Vault
    if bill_file:
        Document.objects.create(
            category=DocCategoryChoices.INVOICE_SCAN,
            file=bill_file,
            file_name=getattr(bill_file, 'name', 'bill_scan'),
            uploaded_by=user,
            invoice=invoice
        )

    # 5. Create Line & Allocations, update Receipts
    receipt_map = {str(r.id): r for r in receipts}
    linked_grn_numbers = []

    for a in allocations_data:
        r = receipt_map[str(a['receipt_id'])]
        alloc_amt = Decimal(str(a['allocated_amount']))
        alloc_qty = Decimal(str(a.get('allocated_quantity', '1.000')))

        InvoiceAllocation.objects.create(
            invoice=invoice,
            goods_receipt=r,
            allocated_amount=alloc_amt,
            allocated_quantity=alloc_qty,
            notes=a.get('notes', '')
        )

        # Update receipt state
        r.status = ReceiptStatusChoices.BILL_LINKED
        r.bill_unique_id = bill_id
        r.save(update_fields=['status', 'bill_unique_id', 'updated_at'])
        linked_grn_numbers.append(r.grn_number)

    # 6. Automatic Purchase-to-Accounts Handover Batch
    accounts_user = User.objects.filter(role='ACCOUNTS').first()
    batch = HandoverBatch.objects.create(
        handover_type=HandoverTypeChoices.PURCHASE_TO_ACCOUNTS,
        unit=unit,
        sender=user,
        sender_name_raw=user.get_full_name() or user.username,
        intended_recipient=accounts_user,
        intended_recipient_name_raw="Accounts Team",
        checklist_summary=f"Bill {bill_id} ({invoice.invoice_number}), Linked GRNs: {', '.join(linked_grn_numbers)}",
        is_acknowledged=False
    )
    HandoverItem.objects.create(batch=batch, invoice=invoice, is_received=True)

    # WorkflowTask for Accounts
    WorkflowTask.objects.create(
        handover_batch=batch,
        task_type=TaskTypeChoices.CUSTODY_ACK,
        title=f"Accounts Custody: Batch {batch.batch_number} (Bill {bill_id})",
        description=f"Acknowledge physical packet for invoice {invoice.invoice_number} from {user.get_full_name() or user.username}",
        assigned_to=accounts_user or user,
        unit=unit,
        invoice=invoice,
        deadline=timezone.now() + timedelta(hours=4),
        status=TaskStatusChoices.OPEN
    )

    # 7. Audit Trail
    AuditEvent.objects.create(
        actor=user,
        actor_username=user.username,
        action="ALLOCATE_AND_SUBMIT_INVOICE",
        entity_type="Invoice",
        entity_id=str(invoice.id),
        business_reference=invoice.bill_unique_id,
        after_state={
            "bill_id": invoice.bill_unique_id,
            "invoice_number": invoice.invoice_number,
            "gross_amount": str(invoice.gross_amount),
            "linked_receipts_count": len(receipts),
            "linked_grns": linked_grn_numbers
        },
        ip_address=ip_address
    )

    # 8. Outbox Event
    OutboxEvent.objects.create(
        event_type="PURCHASE_BILL_SUBMITTED",
        recipient_name="Accounts Department",
        recipient_email=accounts_user.email if accounts_user else "accounts@aef.edu.in",
        subject=f"New Bill Submitted to Accounts: {bill_id} - ₹{invoice.gross_amount}",
        payload={
            "bill_id": bill_id,
            "invoice_number": invoice.invoice_number,
            "amount": str(invoice.gross_amount),
            "unit": unit.name,
            "linked_grns": linked_grn_numbers
        }
    )

    return invoice

@transaction.atomic
def submit_na_invoice(user, invoice_data, bill_file=None, ip_address=None):
    """
    Submits a Direct / Non-PO invoice without linking to a prior Store receipt.
    Generates both NA-XXXXX and BILL-XXXXX references.
    """
    unit_id = invoice_data.get('unit_id')
    unit = Unit.objects.get(id=unit_id) if unit_id else user.primary_unit

    supplier_name = invoice_data.get('supplier_name', '').strip()
    supplier = Supplier.objects.filter(name__iexact=supplier_name).first()

    bill_id = BillSequence.get_next('BILL')
    na_id = BillSequence.get_next('NA')
    gross_amount = Decimal(str(invoice_data.get('gross_amount', '0.00')))

    invoice = Invoice.objects.create(
        bill_unique_id=bill_id,
        na_unique_id=na_id,
        invoice_type=InvoiceTypeChoices.NON_PO,
        unit=unit,
        supplier=supplier,
        supplier_name_raw=supplier_name,
        supplier_code=invoice_data.get('supplier_code', ''),
        invoice_number=invoice_data.get('invoice_number', '').strip(),
        invoice_date=invoice_data.get('invoice_date'),
        gross_amount=gross_amount,
        tax_amount=Decimal(str(invoice_data.get('tax_amount', '0.00'))),
        net_amount=gross_amount,
        due_date=invoice_data.get('due_date'),
        payment_category=invoice_data.get('payment_category', 'Credit'),
        grn_received_from_stores_on=invoice_data.get('service_date', timezone.now().date()),
        purchase_remark=invoice_data.get('purchase_remark', ''),
        status=InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS,
        submitted_by=user,
        purchase_person_raw=user.get_full_name() or user.username,
        submitter_email=user.email,
        bill_scan=bill_file
    )

    if bill_file:
        Document.objects.create(
            category=DocCategoryChoices.INVOICE_SCAN,
            file=bill_file,
            file_name=getattr(bill_file, 'name', 'na_bill_scan'),
            uploaded_by=user,
            invoice=invoice
        )

    accounts_user = User.objects.filter(role='ACCOUNTS').first()
    batch = HandoverBatch.objects.create(
        handover_type=HandoverTypeChoices.PURCHASE_TO_ACCOUNTS,
        unit=unit,
        sender=user,
        sender_name_raw=user.get_full_name() or user.username,
        intended_recipient=accounts_user,
        intended_recipient_name_raw="Accounts Team",
        checklist_summary=f"Non-PO Bill {bill_id} (Ref {na_id}, Inv: {invoice.invoice_number})",
        is_acknowledged=False
    )
    HandoverItem.objects.create(batch=batch, invoice=invoice, is_received=True)

    WorkflowTask.objects.create(
        handover_batch=batch,
        task_type=TaskTypeChoices.CUSTODY_ACK,
        title=f"Accounts Custody: Batch {batch.batch_number} (Non-PO Bill {bill_id})",
        description=f"Acknowledge physical packet for Non-PO invoice {invoice.invoice_number}",
        assigned_to=accounts_user or user,
        unit=unit,
        invoice=invoice,
        deadline=timezone.now() + timedelta(hours=4),
        status=TaskStatusChoices.OPEN
    )

    AuditEvent.objects.create(
        actor=user,
        actor_username=user.username,
        action="SUBMIT_NA_INVOICE",
        entity_type="Invoice",
        entity_id=str(invoice.id),
        business_reference=f"{bill_id} / {na_id}",
        after_state={"bill_id": bill_id, "na_id": na_id, "gross_amount": str(gross_amount)},
        ip_address=ip_address
    )

    return invoice

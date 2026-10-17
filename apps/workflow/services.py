from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from apps.organization.models import Unit, User
from apps.procurement.models import Supplier
from apps.receipts.models import GoodsReceipt, ReceiptLine, GoodsReceiptSequence, ReceiptStatusChoices, DocTypeChoices, PaymentCategoryChoices
from apps.invoices.models import Invoice, InvoiceStatusChoices
from apps.workflow.models import (
    HandoverBatch, HandoverItem, HandoverTypeChoices, CustodyAcknowledgment,
    WorkflowTask, TaskTypeChoices, TaskStatusChoices, ExceptionCase, ApprovalDecision
)
from apps.documents.models import AuditEvent, Document, DocCategoryChoices
from apps.operations.models import OutboxEvent

@transaction.atomic
def submit_store_receipt(user, data, invoice_file=None, grn_file=None, ip_address=None):
    """
    Creates an authoritative Store Material Receipt record (ST-XXXXX),
    records line-item quantities, uploads attachments, and logs AuditEvent.
    """
    unit_id = data.get('unit_id') or data.get('unit')
    unit = Unit.objects.get(id=unit_id) if isinstance(unit_id, str) and len(unit_id) > 30 else Unit.objects.get(name=data.get('unit'))

    supplier_name = data.get('supplier', '').strip()
    supplier = Supplier.objects.filter(name__iexact=supplier_name).first()

    st_number = GoodsReceiptSequence.get_next('ST')
    
    receipt = GoodsReceipt.objects.create(
        st_number=st_number,
        unit=unit,
        supplier=supplier,
        supplier_name_raw=supplier_name,
        material_date=data.get('material_date'),
        doc_type=data.get('doc_type', DocTypeChoices.PO),
        po_wo_number=data.get('po_wo_number', ''),
        dc_number=data.get('dc_number', ''),
        grn_number=data.get('grn_number', ''),
        grn_date=data.get('grn_date'),
        description=data.get('description', ''),
        payment_category=data.get('payment_category', PaymentCategoryChoices.CREDIT),
        is_invoice_received=bool(data.get('is_invoice_received')),
        store_remark=data.get('store_remark', ''),
        assigned_purchase_person=data.get('assigned_purchase_person'),
        assigned_purchase_person_raw=data.get('assigned_purchase_person_raw', ''),
        submitted_by=user,
        store_person_raw=user.get_full_name() or user.username,
        submitter_email=user.email,
        status=ReceiptStatusChoices.PENDING_HANDOVER,
        invoice_scan=invoice_file,
        grn_scan=grn_file,
    )

    # Initial receipt line item
    qty = Decimal(str(data.get('quantity', '1.000')))
    unit_price = Decimal(str(data.get('unit_price', '0.00')))
    ReceiptLine.objects.create(
        goods_receipt=receipt,
        item_description=data.get('description', 'Material received'),
        received_quantity=qty,
        accepted_quantity=qty,
        invoiced_quantity=Decimal('0.000'),
        unit_price=unit_price
    )

    # Document Vault records
    if invoice_file:
        Document.objects.create(
            category=DocCategoryChoices.INVOICE_SCAN,
            file=invoice_file,
            file_name=getattr(invoice_file, 'name', 'invoice_scan'),
            uploaded_by=user,
            goods_receipt=receipt
        )
    if grn_file:
        Document.objects.create(
            category=DocCategoryChoices.GRN_SCAN,
            file=grn_file,
            file_name=getattr(grn_file, 'name', 'grn_scan'),
            uploaded_by=user,
            goods_receipt=receipt
        )

    # Audit Trail
    AuditEvent.objects.create(
        actor=user,
        actor_username=user.username,
        action="SUBMIT_STORE_RECEIPT",
        entity_type="GoodsReceipt",
        entity_id=str(receipt.id),
        business_reference=receipt.st_number,
        after_state={
            "st_number": receipt.st_number,
            "unit": unit.name,
            "supplier": supplier_name,
            "grn_number": receipt.grn_number,
            "status": receipt.status
        },
        ip_address=ip_address
    )

    # Outbox Notification Event
    OutboxEvent.objects.create(
        event_type="STORE_RECEIPT_SUBMITTED",
        recipient_name=receipt.assigned_purchase_person_raw or "Purchase Dept",
        recipient_email=receipt.assigned_purchase_person.email if receipt.assigned_purchase_person else "purchase@aef.edu.in",
        subject=f"New Material Receipt: {receipt.st_number} - GRN: {receipt.grn_number}",
        payload={"st_number": receipt.st_number, "grn_number": receipt.grn_number, "unit": unit.name}
    )

    return receipt

@transaction.atomic
def create_handover_batch(sender, handover_type, unit, intended_recipient, item_ids, checklist_summary=""):
    """
    Groups material receipts or invoices into a physical custody handover batch.
    Creates actionable WorkflowTask for intended recipient with an explicit deadline.
    """
    batch = HandoverBatch.objects.create(
        handover_type=handover_type,
        unit=unit,
        sender=sender,
        sender_name_raw=sender.get_full_name() or sender.username,
        intended_recipient=intended_recipient,
        intended_recipient_name_raw=intended_recipient.get_full_name() if intended_recipient else "Department",
        checklist_summary=checklist_summary,
        is_acknowledged=False
    )

    if handover_type == HandoverTypeChoices.STORE_TO_PURCHASE:
        receipts = GoodsReceipt.objects.filter(id__in=item_ids)
        for r in receipts:
            HandoverItem.objects.create(batch=batch, goods_receipt=r, is_received=True)
            r.status = ReceiptStatusChoices.HANDED_OVER
            r.save(update_fields=['status'])
    else:
        invoices = Invoice.objects.filter(id__in=item_ids)
        for inv in invoices:
            HandoverItem.objects.create(batch=batch, invoice=inv, is_received=True)
            inv.status = InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS
            inv.save(update_fields=['status'])

    # Create WorkflowTask
    WorkflowTask.objects.create(
        handover_batch=batch,
        task_type=TaskTypeChoices.CUSTODY_ACK,
        title=f"Custody Acknowledgment: Batch {batch.batch_number}",
        description=f"Verify and acknowledge hardcopy document custody from {batch.sender_name_raw}. Checklist: {checklist_summary}",
        assigned_to=intended_recipient,
        unit=unit,
        deadline=timezone.now() + timedelta(hours=4),
        status=TaskStatusChoices.OPEN
    )

    AuditEvent.objects.create(
        actor=sender,
        actor_username=sender.username,
        action="DISPATCH_HANDOVER_BATCH",
        entity_type="HandoverBatch",
        entity_id=str(batch.id),
        business_reference=batch.batch_number,
        after_state={"batch_number": batch.batch_number, "type": handover_type, "item_count": len(item_ids)}
    )

    OutboxEvent.objects.create(
        event_type="HANDOVER_BATCH_DISPATCHED",
        recipient_name=batch.intended_recipient_name_raw,
        recipient_email=intended_recipient.email if intended_recipient else "accounts@aef.edu.in",
        subject=f"Document Custody Handover: {batch.batch_number} ({batch.get_handover_type_display()})",
        payload={"batch_number": batch.batch_number, "type": handover_type, "item_count": len(item_ids)}
    )

    return batch

@transaction.atomic
def acknowledge_custody(user, batch_id, all_docs_present=True, remarks="", ip_address=None):
    """
    Explicit, authenticated custody acknowledgment.
    Important: Proves physical custody of papers; DOES NOT approve the invoice!
    """
    batch = HandoverBatch.objects.select_for_update().get(id=batch_id)
    if batch.is_acknowledged:
        return batch

    batch.actual_recipient = user
    batch.acknowledged_at = timezone.now()
    batch.is_acknowledged = True
    batch.is_incomplete = not all_docs_present
    batch.incomplete_notes = remarks if not all_docs_present else ""
    batch.save()

    CustodyAcknowledgment.objects.create(
        batch=batch,
        acknowledged_by=user,
        ip_address=ip_address,
        all_documents_present=all_docs_present,
        remarks=remarks
    )

    # Transition linked items
    for item in batch.items.all():
        if item.goods_receipt:
            item.goods_receipt.status = ReceiptStatusChoices.CUSTODY_ACKNOWLEDGED
            item.goods_receipt.save(update_fields=['status'])
        if item.invoice:
            item.invoice.status = InvoiceStatusChoices.CUSTODY_ACKNOWLEDGED
            item.invoice.save(update_fields=['status'])

    # Close the associated custody task
    WorkflowTask.objects.filter(
        handover_batch=batch,
        task_type=TaskTypeChoices.CUSTODY_ACK,
        status=TaskStatusChoices.OPEN
    ).update(status=TaskStatusChoices.COMPLETED, completed_at=timezone.now())

    AuditEvent.objects.create(
        actor=user,
        actor_username=user.username,
        action="ACKNOWLEDGE_CUSTODY",
        entity_type="HandoverBatch",
        entity_id=str(batch.id),
        business_reference=batch.batch_number,
        after_state={"is_acknowledged": True, "all_docs_present": all_docs_present, "remarks": remarks},
        ip_address=ip_address
    )

    OutboxEvent.objects.create(
        event_type="CUSTODY_ACKNOWLEDGED",
        recipient_name=batch.sender_name_raw,
        recipient_email=batch.sender.email,
        subject=f"Custody Confirmed: Batch {batch.batch_number} received by {user.get_full_name() or user.username}",
        payload={"batch_number": batch.batch_number, "recipient": user.username, "all_present": all_docs_present}
    )

    return batch

@transaction.atomic
def verify_invoice(user, invoice_id, notes=""):
    """
    Transitions invoice from custody to Under Verification / Approval Pending.
    """
    invoice = Invoice.objects.select_for_update().get(id=invoice_id)
    invoice.status = InvoiceStatusChoices.APPROVAL_PENDING
    invoice.save(update_fields=['status', 'updated_at'])

    AuditEvent.objects.create(
        actor=user,
        actor_username=user.username,
        action="VERIFY_INVOICE",
        entity_type="Invoice",
        entity_id=str(invoice.id),
        business_reference=invoice.bill_unique_id,
        after_state={"status": invoice.status, "notes": notes}
    )
    return invoice

@transaction.atomic
def return_invoice_for_correction(user, invoice_id, reason):
    """
    Returns an invoice for correction, preserving full history, reason, and assigning task.
    """
    invoice = Invoice.objects.select_for_update().get(id=invoice_id)
    invoice.status = InvoiceStatusChoices.RETURNED_FOR_CORRECTION
    invoice.save(update_fields=['status', 'updated_at'])

    exc = ExceptionCase.objects.create(
        invoice=invoice,
        reason=reason,
        raised_by=user,
        assigned_owner=invoice.submitted_by
    )

    # Correction Task
    WorkflowTask.objects.create(
        invoice=invoice,
        task_type=TaskTypeChoices.CORRECTION,
        title=f"Correction Required: Invoice {invoice.bill_unique_id}",
        description=f"Returned by Accounts ({user.get_full_name() or user.username}). Reason: {reason}",
        assigned_to=invoice.submitted_by,
        unit=invoice.unit,
        deadline=timezone.now() + timedelta(hours=24),
        status=TaskStatusChoices.OPEN
    )

    AuditEvent.objects.create(
        actor=user,
        actor_username=user.username,
        action="RETURN_INVOICE_FOR_CORRECTION",
        entity_type="Invoice",
        entity_id=str(invoice.id),
        business_reference=invoice.bill_unique_id,
        reason=reason,
        after_state={"status": invoice.status, "reason": reason}
    )

    OutboxEvent.objects.create(
        event_type="INVOICE_RETURNED_FOR_CORRECTION",
        recipient_name=invoice.purchase_person_raw,
        recipient_email=invoice.submitter_email or invoice.submitted_by.email,
        subject=f"ACTION REQUIRED: Invoice {invoice.bill_unique_id} ({invoice.invoice_number}) returned for correction",
        payload={"bill_id": invoice.bill_unique_id, "reason": reason, "returned_by": user.username}
    )

    return invoice

@transaction.atomic
def approve_invoice(user, invoice_id, comments=""):
    """
    Records authoritative ApprovalDecision, transitions invoice to APPROVED.
    """
    invoice = Invoice.objects.select_for_update().get(id=invoice_id)
    invoice.status = InvoiceStatusChoices.APPROVED
    invoice.save(update_fields=['status', 'updated_at'])

    ApprovalDecision.objects.create(
        invoice=invoice,
        approver=user,
        decision="APPROVED",
        comments=comments
    )

    AuditEvent.objects.create(
        actor=user,
        actor_username=user.username,
        action="APPROVE_INVOICE",
        entity_type="Invoice",
        entity_id=str(invoice.id),
        business_reference=invoice.bill_unique_id,
        after_state={"status": invoice.status, "comments": comments}
    )

    OutboxEvent.objects.create(
        event_type="INVOICE_APPROVED",
        recipient_name=invoice.purchase_person_raw,
        recipient_email=invoice.submitter_email or invoice.submitted_by.email,
        subject=f"Approved: Invoice {invoice.bill_unique_id} - ₹{invoice.gross_amount}",
        payload={"bill_id": invoice.bill_unique_id, "approver": user.username, "amount": str(invoice.gross_amount)}
    )

    return invoice

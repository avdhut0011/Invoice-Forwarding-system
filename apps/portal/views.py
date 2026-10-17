from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.http import HttpResponse

from apps.organization.models import Unit, User, RoleChoices
from apps.procurement.models import Supplier, PurchaseOrder
from apps.receipts.models import GoodsReceipt, ReceiptStatusChoices
from apps.invoices.models import Invoice, InvoiceStatusChoices
from apps.workflow.models import HandoverBatch, HandoverTypeChoices, WorkflowTask, TaskStatusChoices
from apps.workflow.services import (
    submit_store_receipt, create_handover_batch, acknowledge_custody,
    approve_invoice, return_invoice_for_correction
)
from apps.invoices.services import allocate_and_submit_invoice, submit_na_invoice

def login_view(request):
    if request.user.is_authenticated:
        return redirect('portal:dashboard')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
            return redirect('portal:dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'registration/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect('portal:login')

@login_required
def dashboard_view(request):
    units = Unit.objects.filter(is_active=True).order_by('name')
    query = request.GET.get('q', '').strip()
    selected_unit = request.GET.get('unit', '').strip()
    selected_status = request.GET.get('status', '').strip()

    receipts_qs = GoodsReceipt.objects.select_related('unit', 'supplier', 'submitted_by').all()
    invoices_qs = Invoice.objects.all()

    # KPI Metrics
    total_receipts = receipts_qs.count()
    pending_custody = receipts_qs.filter(status__in=[ReceiptStatusChoices.PENDING_HANDOVER, ReceiptStatusChoices.HANDED_OVER]).count()
    unbilled_grns = receipts_qs.filter(status=ReceiptStatusChoices.CUSTODY_ACKNOWLEDGED).count()
    in_accounts = invoices_qs.filter(status__in=[InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS, InvoiceStatusChoices.CUSTODY_ACKNOWLEDGED, InvoiceStatusChoices.UNDER_VERIFICATION, InvoiceStatusChoices.APPROVAL_PENDING]).count()
    total_liability = invoices_qs.aggregate(s=Sum('gross_amount'))['s'] or Decimal('0.00')

    # Apply filters
    if query:
        receipts_qs = receipts_qs.filter(
            Q(st_number__icontains=query) |
            Q(grn_number__icontains=query) |
            Q(po_wo_number__icontains=query) |
            Q(supplier_name_raw__icontains=query) |
            Q(bill_unique_id__icontains=query)
        )
    if selected_unit:
        receipts_qs = receipts_qs.filter(unit_id=selected_unit)
    if selected_status:
        receipts_qs = receipts_qs.filter(status=selected_status)

    receipts = receipts_qs.order_by('-created_at')[:100]

    context = {
        'units': units,
        'query': query,
        'selected_unit': selected_unit,
        'selected_status': selected_status,
        'receipts': receipts,
        'total_receipts': total_receipts,
        'pending_custody': pending_custody,
        'unbilled_grns': unbilled_grns,
        'in_accounts': in_accounts,
        'total_liability': total_liability,
    }
    return render(request, 'portal/dashboard.html', context)

@login_required
def store_portal_view(request):
    units = Unit.objects.filter(is_active=True).order_by('name')
    suppliers = Supplier.objects.filter(is_active=True).order_by('name')
    purchase_staff = User.objects.filter(role__in=[RoleChoices.PURCHASE, RoleChoices.ADMIN]).order_by('first_name')
    
    pending_handovers = GoodsReceipt.objects.filter(status=ReceiptStatusChoices.PENDING_HANDOVER).order_by('-created_at')
    recent_receipts = GoodsReceipt.objects.all().order_by('-created_at')[:25]

    context = {
        'units': units,
        'suppliers': suppliers,
        'purchase_staff': purchase_staff,
        'pending_handovers': pending_handovers,
        'recent_receipts': recent_receipts,
    }
    return render(request, 'portal/store_portal.html', context)

@login_required
def store_submit_view(request):
    if request.method == 'POST':
        try:
            purchase_person_id = request.POST.get('assigned_purchase_person_id')
            assigned_user = User.objects.filter(id=purchase_person_id).first() if purchase_person_id else None

            data = {
                'unit_id': request.POST.get('unit_id'),
                'material_date': request.POST.get('material_date'),
                'supplier': request.POST.get('supplier'),
                'doc_type': request.POST.get('doc_type'),
                'po_wo_number': request.POST.get('po_wo_number'),
                'dc_number': request.POST.get('dc_number'),
                'grn_number': request.POST.get('grn_number'),
                'grn_date': request.POST.get('grn_date'),
                'payment_category': request.POST.get('payment_category'),
                'is_invoice_received': request.POST.get('is_invoice_received') == '1',
                'description': request.POST.get('description'),
                'store_remark': request.POST.get('store_remark'),
                'assigned_purchase_person': assigned_user,
                'assigned_purchase_person_raw': assigned_user.get_full_name() if assigned_user else '',
            }
            invoice_file = request.FILES.get('invoice_scan')
            grn_file = request.FILES.get('grn_scan')

            receipt = submit_store_receipt(
                user=request.user,
                data=data,
                invoice_file=invoice_file,
                grn_file=grn_file,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            messages.success(request, f"Material receipt {receipt.st_number} successfully recorded for GRN {receipt.grn_number}!")
        except Exception as e:
            messages.error(request, f"Submission error: {str(e)}")
    return redirect('portal:store_portal')

@login_required
def store_handover_view(request):
    if request.method == 'POST':
        try:
            recipient_id = request.POST.get('recipient_id')
            recipient = get_object_or_404(User, id=recipient_id)
            receipt_ids = request.POST.getlist('receipt_ids')
            checklist = request.POST.get('checklist', '')

            if not receipt_ids:
                messages.warning(request, "Please select at least one receipt to hand over.")
                return redirect('portal:store_portal')

            first_receipt = GoodsReceipt.objects.get(id=receipt_ids[0])
            batch = create_handover_batch(
                sender=request.user,
                handover_type=HandoverTypeChoices.STORE_TO_PURCHASE,
                unit=first_receipt.unit,
                intended_recipient=recipient,
                item_ids=receipt_ids,
                checklist_summary=checklist
            )
            messages.success(request, f"Handover batch {batch.batch_number} created with {len(receipt_ids)} receipt(s) and dispatched to {recipient.get_full_name()}!")
        except Exception as e:
            messages.error(request, f"Handover error: {str(e)}")
    return redirect('portal:store_portal')

@login_required
def purchase_portal_view(request):
    units = Unit.objects.filter(is_active=True).order_by('name')
    incoming_batches = HandoverBatch.objects.filter(
        handover_type=HandoverTypeChoices.STORE_TO_PURCHASE,
        is_acknowledged=False
    ).order_by('-dispatched_at')

    context = {
        'units': units,
        'incoming_batches': incoming_batches,
        'pending_custody_count': incoming_batches.count(),
    }
    return render(request, 'portal/purchase_portal.html', context)

@login_required
def purchase_search_po_view(request):
    """
    HTMX partial view: Searches for unbilled GRNs matching a PO number.
    """
    po_number = request.GET.get('po_number', '').strip()
    receipts = []
    if po_number:
        receipts = GoodsReceipt.objects.filter(
            po_wo_number__icontains=po_number,
            status__in=[ReceiptStatusChoices.CUSTODY_ACKNOWLEDGED, ReceiptStatusChoices.PENDING_HANDOVER, ReceiptStatusChoices.HANDED_OVER]
        ).exclude(status=ReceiptStatusChoices.BILL_LINKED).order_by('-created_at')

    return render(request, 'portal/partials/po_search_results.html', {'receipts': receipts})

@login_required
def purchase_bill_submit_view(request):
    if request.method == 'POST':
        mode = request.POST.get('mode', 'search')
        try:
            bill_file = request.FILES.get('bill_scan')
            gross_amount = Decimal(str(request.POST.get('bill_amount', '0.00')))

            if mode == 'na':
                invoice_data = {
                    'unit_id': request.POST.get('unit_id'),
                    'supplier_name': request.POST.get('supplier_name'),
                    'invoice_number': request.POST.get('bill_number'),
                    'invoice_date': request.POST.get('bill_date'),
                    'gross_amount': gross_amount,
                    'tax_amount': Decimal('0.00'),
                    'due_date': request.POST.get('due_date') or None,
                    'payment_category': request.POST.get('payment_category', 'Credit'),
                    'purchase_remark': request.POST.get('remark', ''),
                }
                inv = submit_na_invoice(user=request.user, invoice_data=invoice_data, bill_file=bill_file, ip_address=request.META.get('REMOTE_ADDR'))
                messages.success(request, f"Direct Bill {inv.bill_unique_id} ({inv.na_unique_id}) successfully submitted to Accounts!")
            else:
                receipt_ids = request.POST.getlist('selected_receipt_ids')
                if not receipt_ids:
                    messages.error(request, "No GRN records selected. Please search and select at least one GRN.")
                    return redirect('portal:purchase_portal')

                # Calculate allocation per receipt (split equally or based on selected count)
                alloc_share = (gross_amount / len(receipt_ids)).quantize(Decimal('0.01'))
                remainder = gross_amount - (alloc_share * len(receipt_ids))

                allocations_data = []
                for i, rid in enumerate(receipt_ids):
                    amt = alloc_share + (remainder if i == 0 else Decimal('0.00'))
                    allocations_data.append({
                        'receipt_id': rid,
                        'allocated_amount': amt,
                        'allocated_quantity': Decimal('1.000'),
                        'notes': f"Allocated against Bill {request.POST.get('bill_number')}"
                    })

                invoice_data = {
                    'invoice_number': request.POST.get('bill_number'),
                    'invoice_date': request.POST.get('bill_date'),
                    'gross_amount': gross_amount,
                    'tax_amount': Decimal('0.00'),
                    'due_date': request.POST.get('due_date') or None,
                    'supplier_code': request.POST.get('supplier_code', ''),
                    'grn_received_from_stores_on': request.POST.get('grn_received_on') or None,
                    'purchase_remark': request.POST.get('remark', ''),
                }

                inv = allocate_and_submit_invoice(
                    user=request.user,
                    invoice_data=invoice_data,
                    allocations_data=allocations_data,
                    bill_file=bill_file,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                messages.success(request, f"Bill {inv.bill_unique_id} successfully linked across {len(receipt_ids)} GRN(s) and forwarded to Accounts!")

        except Exception as e:
            messages.error(request, f"Bill submission error: {str(e)}")

    return redirect('portal:purchase_portal')

@login_required
def purchase_ack_custody_view(request):
    if request.method == 'POST':
        batch_id = request.POST.get('batch_id')
        all_present = request.POST.get('all_present') == '1'
        remarks = request.POST.get('remarks', '')
        try:
            batch = acknowledge_custody(
                user=request.user,
                batch_id=batch_id,
                all_docs_present=all_present,
                remarks=remarks,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            messages.success(request, f"Physical custody of Batch {batch.batch_number} confirmed! Linked GRNs are now ready for billing.")
        except Exception as e:
            messages.error(request, f"Custody acknowledgment error: {str(e)}")
    return redirect('portal:purchase_portal')

@login_required
def accounts_portal_view(request):
    incoming_batches = HandoverBatch.objects.filter(
        handover_type=HandoverTypeChoices.PURCHASE_TO_ACCOUNTS,
        is_acknowledged=False
    ).order_by('-dispatched_at')

    pending_invoices = Invoice.objects.filter(
        status__in=[
            InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS,
            InvoiceStatusChoices.CUSTODY_ACKNOWLEDGED,
            InvoiceStatusChoices.UNDER_VERIFICATION,
            InvoiceStatusChoices.APPROVAL_PENDING,
            InvoiceStatusChoices.RETURNED_FOR_CORRECTION
        ]
    ).prefetch_related('allocations__goods_receipt').order_by('-created_at')

    context = {
        'incoming_batches': incoming_batches,
        'pending_invoices': pending_invoices,
    }
    return render(request, 'portal/accounts_portal.html', context)

@login_required
def accounts_ack_custody_view(request):
    if request.method == 'POST':
        batch_id = request.POST.get('batch_id')
        try:
            batch = acknowledge_custody(
                user=request.user,
                batch_id=batch_id,
                all_docs_present=True,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            messages.success(request, f"Physical custody of Batch {batch.batch_number} confirmed by Accounts!")
        except Exception as e:
            messages.error(request, f"Custody error: {str(e)}")
    return redirect('portal:accounts_portal')

@login_required
def accounts_approve_view(request):
    if request.method == 'POST':
        invoice_id = request.POST.get('invoice_id')
        comments = request.POST.get('comments', '')
        try:
            inv = approve_invoice(user=request.user, invoice_id=invoice_id, comments=comments)
            messages.success(request, f"Invoice {inv.bill_unique_id} (₹{inv.gross_amount}) has been successfully approved!")
        except Exception as e:
            messages.error(request, f"Approval error: {str(e)}")
    return redirect('portal:accounts_portal')

@login_required
def accounts_return_view(request):
    if request.method == 'POST':
        invoice_id = request.POST.get('invoice_id')
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, "A reason must be provided when returning an invoice for correction.")
            return redirect('portal:accounts_portal')
        try:
            inv = return_invoice_for_correction(user=request.user, invoice_id=invoice_id, reason=reason)
            messages.warning(request, f"Invoice {inv.bill_unique_id} has been returned for correction to {inv.purchase_person_raw}.")
        except Exception as e:
            messages.error(request, f"Return error: {str(e)}")
    return redirect('portal:accounts_portal')

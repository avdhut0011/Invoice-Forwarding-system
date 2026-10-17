from decimal import Decimal
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

from apps.receipts.models import GoodsReceipt, ReceiptStatusChoices
from apps.invoices.models import Invoice, InvoiceStatusChoices
from apps.workflow.models import HandoverBatch, WorkflowTask, ApprovalThreshold
from apps.workflow.services import (
    submit_store_receipt, acknowledge_custody, approve_invoice,
    return_invoice_for_correction
)
from apps.invoices.services import allocate_and_submit_invoice, submit_na_invoice
from .serializers import (
    GoodsReceiptSerializer, InvoiceSerializer, HandoverBatchSerializer,
    WorkflowTaskSerializer, ApprovalThresholdSerializer
)
from .permissions import IsUnitAuthorized, CanApproveInvoice

class GoodsReceiptViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing GoodsReceipt records (ST-XXXXX).
    Enforces unit-level authorization.
    """
    queryset = GoodsReceipt.objects.select_related('unit', 'supplier', 'assigned_purchase_person', 'submitted_by').all()
    serializer_class = GoodsReceiptSerializer
    permission_classes = [permissions.IsAuthenticated, IsUnitAuthorized]

    def get_queryset(self):
        qs = super().get_queryset()
        unit_id = self.request.query_params.get('unit')
        status_val = self.request.query_params.get('status')
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        if status_val:
            qs = qs.filter(status=status_val)
        return qs

    def create(self, request, *args, **kwargs):
        try:
            data = request.data.copy()
            invoice_file = request.FILES.get('invoice_scan')
            grn_file = request.FILES.get('grn_scan')

            receipt = submit_store_receipt(
                user=request.user,
                data=data,
                invoice_file=invoice_file,
                grn_file=grn_file,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            serializer = self.get_serializer(receipt)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class InvoiceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for authoritative Invoice records (BILL-XXXXX).
    Supports multi-GRN allocation, tiered approval, returns, and cancellation.
    """
    queryset = Invoice.objects.select_related('unit', 'supplier', 'submitted_by').prefetch_related('allocations__goods_receipt', 'approval_steps').all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsUnitAuthorized]

    def get_queryset(self):
        qs = super().get_queryset()
        status_val = self.request.query_params.get('status')
        unit_id = self.request.query_params.get('unit')
        if status_val:
            qs = qs.filter(status=status_val)
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        return qs

    def create(self, request, *args, **kwargs):
        """
        Create invoice:
        - If mode == 'na': Non-PO direct invoice
        - Else: Allocates across selected GoodsReceipts
        """
        mode = request.data.get('mode', 'search')
        bill_file = request.FILES.get('bill_scan')
        try:
            if mode == 'na':
                inv = submit_na_invoice(
                    user=request.user,
                    invoice_data=request.data,
                    bill_file=bill_file,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
            else:
                allocations_data = request.data.get('allocations', [])
                if not allocations_data:
                    return Response({'error': 'allocations list is required in search mode.'}, status=status.HTTP_400_BAD_REQUEST)

                inv = allocate_and_submit_invoice(
                    user=request.user,
                    invoice_data=request.data,
                    allocations_data=allocations_data,
                    bill_file=bill_file,
                    ip_address=request.META.get('REMOTE_ADDR')
                )

            serializer = self.get_serializer(inv)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[CanApproveInvoice])
    def approve(self, request, pk=None):
        """
        POST /api/invoices/{id}/approve/
        Progresses through the hierarchical approval matrix.
        """
        comments = request.data.get('comments', '')
        try:
            inv = approve_invoice(user=request.user, invoice_id=pk, comments=comments)
            serializer = self.get_serializer(inv)
            return Response({
                'message': f"Approval step completed for {inv.bill_unique_id}.",
                'invoice': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[CanApproveInvoice])
    def return_for_correction(self, request, pk=None):
        """
        POST /api/invoices/{id}/return_for_correction/
        Returns an invoice for correction, creating an ExceptionCase and task.
        """
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'error': 'A reason is required to return an invoice.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            inv = return_invoice_for_correction(user=request.user, invoice_id=pk, reason=reason)
            serializer = self.get_serializer(inv)
            return Response({
                'message': f"Invoice {inv.bill_unique_id} returned for correction.",
                'invoice': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        POST /api/invoices/{id}/cancel/
        Controlled cancellation of an invoice, reversing linked receipt states.
        """
        inv = self.get_object()
        if inv.status == InvoiceStatusChoices.APPROVED and not request.user.is_superuser:
            return Response({'error': 'Only administrators can cancel an approved invoice.'}, status=status.HTTP_403_FORBIDDEN)

        # Release linked receipts
        for alloc in inv.allocations.all():
            r = alloc.goods_receipt
            r.status = ReceiptStatusChoices.CUSTODY_ACKNOWLEDGED
            r.bill_unique_id = None
            r.save(update_fields=['status', 'bill_unique_id', 'updated_at'])

        inv.status = InvoiceStatusChoices.CANCELLED
        inv.save(update_fields=['status', 'updated_at'])

        serializer = self.get_serializer(inv)
        return Response({'message': f"Invoice {inv.bill_unique_id} cancelled.", 'invoice': serializer.data})

class HandoverBatchViewSet(viewsets.ModelViewSet):
    """
    API endpoint for physical document custody Handover Batches (HB-XXXXX).
    """
    queryset = HandoverBatch.objects.select_related('unit', 'sender', 'intended_recipient', 'actual_recipient').prefetch_related('items').all()
    serializer_class = HandoverBatchSerializer
    permission_classes = [permissions.IsAuthenticated, IsUnitAuthorized]

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """
        POST /api/handovers/{id}/acknowledge/
        Explicitly acknowledges hardcopy custody of the packet.
        """
        all_present = request.data.get('all_documents_present', True)
        remarks = request.data.get('remarks', '')
        try:
            batch = acknowledge_custody(
                user=request.user,
                batch_id=pk,
                all_docs_present=all_present,
                remarks=remarks,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            serializer = self.get_serializer(batch)
            return Response({
                'message': f"Physical custody of Batch {batch.batch_number} successfully acknowledged.",
                'batch': serializer.data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WorkflowTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for inspecting active SLA Workflow Tasks.
    """
    queryset = WorkflowTask.objects.select_related('unit', 'assigned_to').all()
    serializer_class = WorkflowTaskSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def my_tasks(self, request):
        tasks = self.get_queryset().filter(assigned_to=request.user, status='OPEN').order_by('deadline')
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

class ApprovalThresholdViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for inspecting the multi-tier approval matrix rules.
    """
    queryset = ApprovalThreshold.objects.filter(is_active=True).order_by('tier_level')
    serializer_class = ApprovalThresholdSerializer
    permission_classes = [permissions.IsAuthenticated]

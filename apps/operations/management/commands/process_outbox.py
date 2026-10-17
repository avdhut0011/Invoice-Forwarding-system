import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from apps.operations.models import OutboxEvent, DeliveryAttempt, OutboxStatusChoices

class Command(BaseCommand):
    help = 'Processes pending outbox notification events, renders live HTML templates, and dispatches emails'

    def add_arguments(self, parser):
        parser.add_argument('--run-once', action='store_true', help='Process pending events once and exit')
        parser.add_argument('--interval', type=int, default=10, help='Polling interval in seconds (default: 10)')

    def handle(self, *args, **options):
        run_once = options['run_once']
        interval = options['interval']

        self.stdout.write(self.style.NOTICE("Starting Outbox HTML Email Dispatcher..."))

        while True:
            processed_count = self.process_pending_events()
            if processed_count > 0:
                self.stdout.write(self.style.SUCCESS(f"Successfully dispatched {processed_count} HTML notification email(s)."))
            
            if run_once:
                break
            
            time.sleep(interval)

    def process_pending_events(self):
        with transaction.atomic():
            events = list(
                OutboxEvent.objects.select_for_update(skip_locked=True)
                .filter(status=OutboxStatusChoices.PENDING, next_retry_at__lte=timezone.now())[:50]
            )
            
            for event in events:
                event.status = OutboxStatusChoices.PROCESSING
                event.save(update_fields=['status'])

        count = 0
        site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')

        for event in events:
            attempt_num = event.retry_count + 1
            try:
                # 1. Map event type to HTML template & context
                template_name = None
                context = {
                    'recipient_name': event.recipient_name or 'Team Member',
                    'subject': event.subject,
                    'site_url': site_url,
                    **event.payload
                }

                if event.event_type in ['STORE_RECEIPT_SUBMITTED', 'HANDOVER_BATCH_DISPATCHED']:
                    template_name = 'emails/store_to_purchase_handover.html'
                    context.setdefault('action_url', f"{site_url}/purchase/")
                    context.setdefault('batch_number', event.payload.get('batch_number', 'HB-PENDING'))
                    context.setdefault('unit_name', event.payload.get('unit', 'Ashoka Universal School'))
                    context.setdefault('sender_name', 'Store Department')
                    context.setdefault('dispatched_at', timezone.now().strftime('%d/%m/%Y %H:%M'))
                    context.setdefault('checklist_summary', event.payload.get('checklist', 'Physical material receipt documents'))
                    context.setdefault('deadline', 'Within 4 business hours')
                elif event.event_type == 'PURCHASE_BILL_SUBMITTED':
                    template_name = 'emails/purchase_to_accounts_handover.html'
                    context.setdefault('action_url', f"{site_url}/accounts/")
                    context.setdefault('sender_name', 'Purchase Department')
                    context.setdefault('supplier_name', event.payload.get('supplier', 'Supplier'))
                    context.setdefault('invoice_number', event.payload.get('invoice_number', 'N/A'))
                    context.setdefault('unit_name', event.payload.get('unit', 'Ashoka Universal School'))
                    context.setdefault('linked_grns', ', '.join(event.payload.get('linked_grns', [])) or 'Direct Bill')
                    context.setdefault('due_date', event.payload.get('due_date', '-'))
                elif event.event_type == 'INVOICE_RETURNED_FOR_CORRECTION':
                    template_name = 'emails/invoice_returned.html'
                    context.setdefault('action_url', f"{site_url}/purchase/")
                    context.setdefault('returned_by', event.payload.get('returned_by', 'Accounts Team'))
                    context.setdefault('reason', event.payload.get('reason', 'Verification discrepancy'))
                elif event.event_type == 'INVOICE_APPROVED':
                    template_name = 'emails/invoice_approved.html'
                    context.setdefault('action_url', f"{site_url}/")
                    context.setdefault('approver', event.payload.get('final_approver', 'Finance Authority'))

                if template_name:
                    html_content = render_to_string(template_name, context)
                    text_content = strip_tags(html_content)
                else:
                    html_content = f"<p>{event.subject}</p>"
                    text_content = event.subject

                # 2. Dispatch real multipart email
                recipient = event.recipient_email or 'system.developer@ausindia.org'
                msg = EmailMultiAlternatives(
                    subject=event.subject,
                    body=text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[recipient]
                )
                msg.attach_alternative(html_content, "text/html")
                msg.send(fail_silently=False)

                self.stdout.write(f"Delivered HTML email: [{event.event_type}] to {recipient} - '{event.subject}'")

                DeliveryAttempt.objects.create(
                    outbox_event=event,
                    attempt_number=attempt_num,
                    success=True
                )
                event.status = OutboxStatusChoices.DELIVERED
                event.delivered_at = timezone.now()
                event.save(update_fields=['status', 'delivered_at'])
                count += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Delivery failed for {event.id}: {str(e)}"))
                DeliveryAttempt.objects.create(
                    outbox_event=event,
                    attempt_number=attempt_num,
                    success=False,
                    error_message=str(e)
                )
                event.retry_count = attempt_num
                event.last_error = str(e)
                if event.retry_count >= 5:
                    event.status = OutboxStatusChoices.FAILED
                else:
                    event.status = OutboxStatusChoices.PENDING
                    event.next_retry_at = timezone.now() + timezone.timedelta(seconds=2 ** event.retry_count * 10)
                event.save(update_fields=['status', 'retry_count', 'last_error', 'next_retry_at'])

        return count

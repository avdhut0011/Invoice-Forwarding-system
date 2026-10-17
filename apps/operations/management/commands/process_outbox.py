import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from apps.operations.models import OutboxEvent, DeliveryAttempt, OutboxStatusChoices

class Command(BaseCommand):
    help = 'Processes pending outbox notification events with retry logic and delivery logging'

    def add_arguments(self, parser):
        parser.add_argument('--run-once', action='store_true', help='Process pending events once and exit')
        parser.add_argument('--interval', type=int, default=10, help='Polling interval in seconds (default: 10)')

    def handle(self, *args, **options):
        run_once = options['run_once']
        interval = options['interval']

        self.stdout.write(self.style.NOTICE("Starting Outbox Event Dispatcher..."))

        while True:
            processed_count = self.process_pending_events()
            if processed_count > 0:
                self.stdout.write(self.style.SUCCESS(f"Processed {processed_count} outbox event(s)."))
            
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
        for event in events:
            attempt_num = event.retry_count + 1
            try:
                # Simulated reliable delivery / Email dispatch
                # In production: send_mail(event.subject, event.body, ...)
                self.stdout.write(f"Delivering [{event.event_type}] to {event.recipient_email} - '{event.subject}'")

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

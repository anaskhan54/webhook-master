import requests
import logging
import hmac
import hashlib
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from django.db.models import Q
from django.core.cache import cache

from .models import Webhook, DeliveryAttempt, Subscription

logger = logging.getLogger(__name__)

@shared_task
def process_webhook_delivery(webhook_id):
    """
    Process the delivery of a webhook to its target URL.
    This task is triggered when a webhook is ingested.
    """
    try:
        logger.info(f"Processing webhook delivery: {webhook_id}")
        
        # Ensure webhook_id is treated as string if it's passed as list
        if isinstance(webhook_id, list) and len(webhook_id) > 0:
            webhook_id = webhook_id[0]
        
        webhook = Webhook.objects.select_related('subscription').get(id=webhook_id)
        
        # Update status to in progress
        webhook.status = 'IN_PROGRESS'
        webhook.save(update_fields=['status'])
        
        # Try to get subscription from cache or database
        subscription = cache.get(f"subscription_{webhook.subscription.id}")
        if not subscription:
            subscription = webhook.subscription
            # Cache subscription for future use
            cache.set(f"subscription_{subscription.id}", subscription, timeout=3600)
        
        # Attempt to deliver the webhook
        _deliver_webhook(webhook)
        
    except Webhook.DoesNotExist:
        logger.error(f"Webhook {webhook_id} not found")
    except Exception as e:
        logger.exception(f"Error processing webhook {webhook_id}: {str(e)}")
        # If there's an error in the task itself, mark webhook as failed
        try:
            Webhook.objects.filter(id=webhook_id).update(
                status='FAILED',
                retry_count=5  # Max retries to prevent further attempts
            )
        except Exception as update_error:
            logger.exception(f"Error updating webhook status: {str(update_error)}")

def _deliver_webhook(webhook):
    """Helper function to deliver a webhook to its target URL"""
    subscription = webhook.subscription
    target_url = subscription.target_url
    
    # Get the appropriate headers
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'WebhookMaster-Delivery/1.0',
        'X-Webhook-ID': str(webhook.id)
    }
    
    # Add signature if secret key is provided
    if subscription.secret_key:
        # Calculate signature
        payload_bytes = str(webhook.payload).encode('utf-8')
        signature = hmac.new(
            subscription.secret_key.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        headers['X-Hub-Signature-256'] = f'sha256={signature}'
    
    # Add event type if present
    if webhook.event_type:
        headers['X-Webhook-Event'] = webhook.event_type
    
    try:
        # Attempt delivery with timeout
        response = requests.post(
            target_url,
            json=webhook.payload,
            headers=headers,
            timeout=settings.WEBHOOK_DELIVERY_TIMEOUT
        )
        
        # Log the attempt
        is_success = 200 <= response.status_code < 300
        attempt = DeliveryAttempt.objects.create(
            webhook=webhook,
            attempt_number=webhook.retry_count + 1,
            status_code=response.status_code,
            error_detail='' if is_success else response.text[:1000],
            is_success=is_success
        )
        
        if is_success:
            # Successful delivery
            webhook.status = 'DELIVERED'
            webhook.save(update_fields=['status'])
            logger.info(f"Webhook {webhook.id} delivered successfully")
        else:
            # Failed but can retry
            _schedule_retry(webhook)
            
    except requests.RequestException as e:
        # Network error, timeout, etc.
        attempt = DeliveryAttempt.objects.create(
            webhook=webhook,
            attempt_number=webhook.retry_count + 1,
            status_code=None,
            error_detail=str(e)[:1000],
            is_success=False
        )
        
        # Schedule retry
        _schedule_retry(webhook)

def _schedule_retry(webhook):
    """Schedule a retry for a failed webhook delivery"""
    max_retries = settings.WEBHOOK_MAX_RETRIES
    retry_backoff = settings.WEBHOOK_RETRY_BACKOFF
    
    # Increment retry count
    webhook.retry_count += 1
    
    if webhook.retry_count >= max_retries:
        # Max retries reached, mark as failed
        webhook.status = 'FAILED'
        webhook.next_retry_at = None
        webhook.save(update_fields=['status', 'retry_count', 'next_retry_at'])
        logger.warning(f"Webhook {webhook.id} failed after {max_retries} attempts")
    else:
        # Schedule next retry
        backoff_index = min(webhook.retry_count - 1, len(retry_backoff) - 1)
        retry_delay = retry_backoff[backoff_index]
        
        webhook.next_retry_at = timezone.now() + timedelta(seconds=retry_delay)
        webhook.status = 'PENDING'
        webhook.save(update_fields=['status', 'retry_count', 'next_retry_at'])
        
        logger.info(f"Scheduling retry {webhook.retry_count} for webhook {webhook.id} in {retry_delay}s")
        
        try:
            # Schedule the retry task
            retry_webhook_delivery.apply_async(
                args=[str(webhook.id)],
                eta=webhook.next_retry_at
            )
        except Exception as e:
            logger.exception(f"Error scheduling retry for webhook {webhook.id}: {str(e)}")
            webhook.status = 'FAILED'
            webhook.save(update_fields=['status'])

@shared_task
def retry_webhook_delivery(webhook_id):
    """Retry delivery of a failed webhook"""
    try:
        # Ensure webhook_id is treated as string if it's passed as list
        if isinstance(webhook_id, list) and len(webhook_id) > 0:
            webhook_id = webhook_id[0]
            
        webhook = Webhook.objects.select_related('subscription').get(id=webhook_id)
        _deliver_webhook(webhook)
    except Webhook.DoesNotExist:
        logger.error(f"Webhook {webhook_id} not found for retry")
    except Exception as e:
        logger.exception(f"Error retrying webhook {webhook_id}: {str(e)}")

@shared_task
def retry_pending_webhooks():
    """
    Periodic task to retry pending webhooks that missed their scheduled retry
    This handles cases where Celery workers were down when retries were scheduled
    """
    now = timezone.now()
    
    # Find pending webhooks with retry_at in the past
    pending_webhooks = Webhook.objects.filter(
        status='PENDING',
        next_retry_at__lte=now,
        retry_count__lt=settings.WEBHOOK_MAX_RETRIES
    )
    
    for webhook in pending_webhooks:
        logger.info(f"Enqueueing missed retry for webhook {webhook.id}")
        process_webhook_delivery.delay(str(webhook.id))

@shared_task
def cleanup_old_logs():
    """
    Periodic task to clean up old delivery attempt logs
    This maintains the data retention policy (default 72 hours)
    """
    retention_hours = settings.WEBHOOK_LOG_RETENTION_HOURS
    retention_threshold = timezone.now() - timedelta(hours=retention_hours)
    
    # Delete delivery attempts older than retention period
    old_attempts = DeliveryAttempt.objects.filter(timestamp__lt=retention_threshold)
    count = old_attempts.count()
    if count > 0:
        old_attempts.delete()
        logger.info(f"Cleaned up {count} delivery attempt logs older than {retention_hours} hours") 
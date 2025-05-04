from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock, ANY, call
import datetime
import requests

from api.models import Subscription, Webhook, DeliveryAttempt
from api.tasks import (
    process_webhook_delivery, 
    retry_webhook_delivery, 
    _deliver_webhook, 
    _schedule_retry,
    retry_pending_webhooks,
    cleanup_old_logs
)


class WebhookDeliveryTasksTests(TestCase):
    def setUp(self):
        self.subscription = Subscription.objects.create(
            target_url='https://example.com/webhooks',
            secret_key='test-secret'
        )
        self.webhook = Webhook.objects.create(
            subscription=self.subscription,
            payload={'event': 'test', 'data': {'id': 123}},
            event_type='test.event',
            status='PENDING'
        )

    @patch('api.tasks.Webhook.objects.select_related')
    @patch('api.tasks._deliver_webhook')
    def test_process_webhook_delivery(self, mock_deliver, mock_select_related):
        """Test the process_webhook_delivery task"""
        # Mock the database query
        mock_manager = MagicMock()
        mock_select_related.return_value = mock_manager
        mock_manager.get.return_value = self.webhook
        
        # Call the task
        process_webhook_delivery(str(self.webhook.id))
        
        # Cannot reliably check webhook status here since it's mocked
        # and the _deliver_webhook mock doesn't update the status
        
        # Verify _deliver_webhook was called
        mock_deliver.assert_called_once_with(self.webhook)

    @patch('requests.post')
    def test_deliver_webhook_success(self, mock_post):
        """Test successful webhook delivery"""
        # Mock a successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        # Call deliver function
        _deliver_webhook(self.webhook)
        
        # Verify webhook was updated
        self.webhook.refresh_from_db()
        self.assertEqual(self.webhook.status, 'DELIVERED')
        
        # Verify delivery attempt was created
        attempts = DeliveryAttempt.objects.filter(webhook=self.webhook)
        self.assertEqual(attempts.count(), 1)
        attempt = attempts.first()
        self.assertEqual(attempt.status_code, 200)
        self.assertTrue(attempt.is_success)
        
        # Verify request was made correctly
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], self.subscription.target_url)
        self.assertEqual(kwargs['json'], self.webhook.payload)
        self.assertIn('Content-Type', kwargs['headers'])
        self.assertIn('X-Webhook-ID', kwargs['headers'])

    @patch('requests.post')
    @patch('api.tasks._schedule_retry')
    def test_deliver_webhook_failure(self, mock_schedule_retry, mock_post):
        """Test failed webhook delivery"""
        # Mock a failed response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response
        
        # Call deliver function
        _deliver_webhook(self.webhook)
        
        # Verify delivery attempt was created with failure
        attempts = DeliveryAttempt.objects.filter(webhook=self.webhook)
        self.assertEqual(attempts.count(), 1)
        attempt = attempts.first()
        self.assertEqual(attempt.status_code, 500)
        self.assertFalse(attempt.is_success)
        
        # Verify retry was scheduled
        mock_schedule_retry.assert_called_once_with(self.webhook)

    @patch('requests.post', side_effect=requests.RequestException("Connection error"))
    @patch('api.tasks._schedule_retry')
    def test_deliver_webhook_exception(self, mock_schedule_retry, mock_post):
        """Test webhook delivery with request exception"""
        # Call deliver function
        _deliver_webhook(self.webhook)
        
        # Verify delivery attempt was created with failure
        attempts = DeliveryAttempt.objects.filter(webhook=self.webhook)
        self.assertEqual(attempts.count(), 1)
        attempt = attempts.first()
        self.assertIsNone(attempt.status_code)  # No status code for network errors
        self.assertEqual(attempt.error_detail, "Connection error")
        self.assertFalse(attempt.is_success)
        
        # Verify retry was scheduled
        mock_schedule_retry.assert_called_once_with(self.webhook)

    @patch('api.tasks.retry_webhook_delivery')
    def test_schedule_retry(self, mock_retry_webhook):
        """Test scheduling retry with correct backoff"""
        # Mock the apply_async method
        mock_apply_async = MagicMock()
        mock_retry_webhook.apply_async = mock_apply_async
        
        # Call schedule_retry
        _schedule_retry(self.webhook)
        
        # Refresh webhook from DB
        self.webhook.refresh_from_db()
        
        # Verify webhook was updated
        self.assertEqual(self.webhook.status, 'PENDING')
        self.assertEqual(self.webhook.retry_count, 1)
        self.assertIsNotNone(self.webhook.next_retry_at)
        
        # Verify retry task was scheduled with the correct arguments
        mock_apply_async.assert_called_once()
        args = mock_apply_async.call_args[0]
        kwargs = mock_apply_async.call_args[1]
        
        self.assertIn('args', kwargs)
        self.assertEqual(kwargs['args'], [str(self.webhook.id)])
        self.assertIn('eta', kwargs)

    @patch('api.tasks.process_webhook_delivery.delay')
    def test_retry_pending_webhooks(self, mock_delay):
        """Test retry_pending_webhooks task"""
        # Create a webhook with next_retry_at in the past
        past_time = timezone.now() - datetime.timedelta(minutes=5)
        webhook = Webhook.objects.create(
            subscription=self.subscription,
            payload={'event': 'test2'},
            status='PENDING',
            next_retry_at=past_time,
            retry_count=1
        )
        
        # Call the task
        retry_pending_webhooks()
        
        # Verify process_webhook_delivery was called
        mock_delay.assert_called_once_with(ANY)
        self.assertEqual(str(mock_delay.call_args[0][0]), str(webhook.id))

    def test_cleanup_old_logs(self):
        """Test cleanup_old_logs task"""
        # Get the current time and create a timestamp in the past
        now = timezone.now()
        old_time = now - datetime.timedelta(hours=100)  # Older than retention period
        
        # Create a webhook and delivery attempt
        webhook = Webhook.objects.create(
            subscription=self.subscription,
            payload={'event': 'old_test'},
            status='DELIVERED'
        )
        
        attempt = DeliveryAttempt.objects.create(
            webhook=webhook,
            attempt_number=1,
            status_code=200,
            error_detail='',
            is_success=True
        )
        
        # Set the timestamp manually since it's auto_now_add
        DeliveryAttempt.objects.filter(id=attempt.id).update(timestamp=old_time)
        
        # Call the task
        with patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = now
            cleanup_old_logs()
        
        # Verify old attempt was deleted
        self.assertEqual(DeliveryAttempt.objects.count(), 0) 
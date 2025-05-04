from django.test import TestCase
from django.utils import timezone
from api.models import Subscription, Webhook, DeliveryAttempt
import uuid


class SubscriptionModelTests(TestCase):
    def setUp(self):
        self.subscription = Subscription.objects.create(
            target_url='https://example.com/webhooks',
            secret_key='test-secret',
            event_types=['order.created', 'user.registered']
        )

    def test_subscription_creation(self):
        """Test the basic creation of a Subscription"""
        self.assertIsInstance(self.subscription.id, uuid.UUID)
        self.assertEqual(self.subscription.target_url, 'https://example.com/webhooks')
        self.assertEqual(self.subscription.secret_key, 'test-secret')
        self.assertEqual(self.subscription.event_types, ['order.created', 'user.registered'])
        self.assertTrue(self.subscription.is_active)

    def test_subscription_string_representation(self):
        """Test the string representation of a Subscription"""
        self.assertEqual(str(self.subscription), f"Subscription {self.subscription.id}")


class WebhookModelTests(TestCase):
    def setUp(self):
        self.subscription = Subscription.objects.create(
            target_url='https://example.com/webhooks',
            secret_key='test-secret'
        )
        self.webhook = Webhook.objects.create(
            subscription=self.subscription,
            payload={'event': 'test', 'data': {'id': 123}},
            event_type='test.event'
        )

    def test_webhook_creation(self):
        """Test the basic creation of a Webhook"""
        self.assertIsInstance(self.webhook.id, uuid.UUID)
        self.assertEqual(self.webhook.subscription, self.subscription)
        self.assertEqual(self.webhook.payload, {'event': 'test', 'data': {'id': 123}})
        self.assertEqual(self.webhook.event_type, 'test.event')
        self.assertEqual(self.webhook.status, 'PENDING')
        self.assertEqual(self.webhook.retry_count, 0)

    def test_webhook_status_choices(self):
        """Test the webhook status options"""
        valid_statuses = [choice[0] for choice in Webhook.STATUS_CHOICES]
        
        # Test each valid status
        for status in valid_statuses:
            self.webhook.status = status
            self.webhook.save()
            refreshed_webhook = Webhook.objects.get(id=self.webhook.id)
            self.assertEqual(refreshed_webhook.status, status)


class DeliveryAttemptModelTests(TestCase):
    def setUp(self):
        self.subscription = Subscription.objects.create(
            target_url='https://example.com/webhooks'
        )
        self.webhook = Webhook.objects.create(
            subscription=self.subscription,
            payload={'event': 'test', 'data': {'id': 123}}
        )
        self.attempt = DeliveryAttempt.objects.create(
            webhook=self.webhook,
            attempt_number=1,
            status_code=200,
            error_detail='',
            is_success=True
        )

    def test_delivery_attempt_creation(self):
        """Test the basic creation of a DeliveryAttempt"""
        self.assertIsInstance(self.attempt.id, uuid.UUID)
        self.assertEqual(self.attempt.webhook, self.webhook)
        self.assertEqual(self.attempt.attempt_number, 1)
        self.assertEqual(self.attempt.status_code, 200)
        self.assertEqual(self.attempt.error_detail, '')
        self.assertTrue(self.attempt.is_success)

    def test_delivery_attempt_failed(self):
        """Test creating a failed delivery attempt"""
        failed_attempt = DeliveryAttempt.objects.create(
            webhook=self.webhook,
            attempt_number=2,
            status_code=500,
            error_detail='Internal Server Error',
            is_success=False
        )
        
        self.assertEqual(failed_attempt.attempt_number, 2)
        self.assertEqual(failed_attempt.status_code, 500)
        self.assertEqual(failed_attempt.error_detail, 'Internal Server Error')
        self.assertFalse(failed_attempt.is_success) 
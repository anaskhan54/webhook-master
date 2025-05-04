from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
import json
import uuid
import hmac
import hashlib
from unittest.mock import patch

from api.models import Subscription, Webhook, DeliveryAttempt


class SubscriptionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.subscription_data = {
            'target_url': 'https://example.com/webhooks',
            'secret_key': 'test-secret',
            'event_types': ['order.created', 'user.registered'],
            'is_active': True
        }
        self.subscription = Subscription.objects.create(**self.subscription_data)

    def test_list_subscriptions(self):
        """Test retrieving a list of subscriptions"""
        url = reverse('subscription-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['target_url'], self.subscription_data['target_url'])

    def test_create_subscription(self):
        """Test creating a new subscription"""
        url = reverse('subscription-list')
        new_subscription = {
            'target_url': 'https://new-example.com/webhooks',
            'secret_key': 'new-secret',
            'event_types': ['product.created'],
            'is_active': True
        }
        
        response = self.client.post(url, new_subscription, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Subscription.objects.count(), 2)
        self.assertEqual(response.data['target_url'], new_subscription['target_url'])
        self.assertEqual(response.data['event_types'], new_subscription['event_types'])

    def test_retrieve_subscription(self):
        """Test retrieving a specific subscription"""
        url = reverse('subscription-detail', args=[str(self.subscription.id)])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['target_url'], self.subscription_data['target_url'])

    def test_update_subscription(self):
        """Test updating a subscription"""
        url = reverse('subscription-detail', args=[str(self.subscription.id)])
        updated_data = {
            'target_url': 'https://updated-example.com/webhooks',
            'secret_key': 'updated-secret',
            'event_types': ['order.updated'],
            'is_active': True
        }
        
        response = self.client.put(url, updated_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.target_url, updated_data['target_url'])
        self.assertEqual(self.subscription.event_types, updated_data['event_types'])

    def test_delete_subscription(self):
        """Test deleting a subscription"""
        url = reverse('subscription-detail', args=[str(self.subscription.id)])
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Subscription.objects.count(), 0)


class WebhookIngestionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.subscription = Subscription.objects.create(
            target_url='https://example.com/webhooks',
            secret_key='test-secret',
            event_types=['order.created', 'order.updated'],
            is_active=True
        )
        self.payload = {
            'event': 'order.created',
            'data': {'id': 123, 'customer': {'name': 'Test Customer'}}
        }

    @patch('api.views.process_webhook_delivery.delay')
    @patch('api.views.cache.get')
    @patch('api.views.cache.set')
    def test_webhook_ingestion(self, mock_cache_set, mock_cache_get, mock_delay):
        """Test ingesting a webhook"""
        # Mock cache to return the subscription
        mock_cache_get.return_value = self.subscription
        
        url = reverse('webhook-ingestion', args=[str(self.subscription.id)])
        
        # Calculate signature for this test
        payload_bytes = json.dumps(self.payload).encode('utf-8')
        signature = hmac.new(
            self.subscription.secret_key.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        # Set signature header
        self.client.credentials(HTTP_X_HUB_SIGNATURE_256=f'sha256={signature}')
        
        # Event type as a query parameter
        response = self.client.post(
            f"{url}?event_type=order.created", 
            self.payload, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('id', response.data)
        self.assertEqual(response.data['status'], 'accepted')
        
        # Verify webhook was created
        webhook_id = response.data['id']
        webhook = Webhook.objects.get(id=webhook_id)
        self.assertEqual(webhook.subscription, self.subscription)
        self.assertEqual(webhook.payload, self.payload)
        self.assertEqual(webhook.event_type, 'order.created')
        self.assertEqual(webhook.status, 'PENDING')
        
        # Verify process_webhook_delivery.delay was called
        mock_delay.assert_called_once()

    @patch('api.views.process_webhook_delivery.delay')
    @patch('api.views.cache.get')
    @patch('api.views.cache.set')
    def test_webhook_ingestion_with_signature(self, mock_cache_set, mock_cache_get, mock_delay):
        """Test ingesting a webhook with signature verification"""
        # Mock cache to return the subscription
        mock_cache_get.return_value = self.subscription
        
        url = reverse('webhook-ingestion', args=[str(self.subscription.id)])
        
        # Calculate signature
        payload_bytes = json.dumps(self.payload).encode('utf-8')
        signature = hmac.new(
            self.subscription.secret_key.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        # Set signature header
        self.client.credentials(HTTP_X_HUB_SIGNATURE_256=f'sha256={signature}')
        
        response = self.client.post(
            f"{url}?event_type=order.created", 
            self.payload, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        
        # Test with invalid signature
        self.client.credentials(HTTP_X_HUB_SIGNATURE_256='sha256=invalid-signature')
        
        response = self.client.post(
            f"{url}?event_type=order.created", 
            self.payload, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('api.views.process_webhook_delivery.delay')
    @patch('api.views.cache.get')
    @patch('api.views.cache.set')
    def test_event_type_filtering(self, mock_cache_set, mock_cache_get, mock_delay):
        """Test event type filtering in webhook ingestion"""
        # Mock cache to return the subscription
        mock_cache_get.return_value = self.subscription
        
        url = reverse('webhook-ingestion', args=[str(self.subscription.id)])
        
        # Test with unsupported event type - this should now return a 400 bad request
        # Calculate signature for this test - unsupported event
        payload_bytes = json.dumps(self.payload).encode('utf-8')
        signature = hmac.new(
            self.subscription.secret_key.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        # Set signature header
        self.client.credentials(HTTP_X_HUB_SIGNATURE_256=f'sha256={signature}')
        
        response = self.client.post(
            f"{url}?event_type=user.created", 
            self.payload, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Test with supported event type - this should return 202 accepted
        # Signature remains the same as payload hasn't changed
        response = self.client.post(
            f"{url}?event_type=order.updated", 
            self.payload, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)


class WebhookStatusTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.subscription = Subscription.objects.create(
            target_url='https://example.com/webhooks'
        )
        self.webhook = Webhook.objects.create(
            subscription=self.subscription,
            payload={'event': 'test', 'data': {'id': 123}},
            event_type='test.event',
            status='PENDING'
        )
        # Create a delivery attempt
        self.attempt = DeliveryAttempt.objects.create(
            webhook=self.webhook,
            attempt_number=1,
            status_code=500,
            error_detail='Server Error',
            is_success=False
        )

    def test_webhook_status(self):
        """Test getting webhook status"""
        url = reverse('webhook-status', args=[str(self.webhook.id)])
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.webhook.id))
        self.assertEqual(response.data['status'], 'PENDING')
        self.assertEqual(len(response.data['delivery_attempts']), 1)
        self.assertEqual(response.data['delivery_attempts'][0]['attempt_number'], 1)
        self.assertEqual(response.data['delivery_attempts'][0]['status_code'], 500)
        self.assertFalse(response.data['delivery_attempts'][0]['is_success'])

    def test_webhook_history(self):
        """Test getting delivery history for a subscription"""
        url = reverse('delivery-history', args=[str(self.subscription.id)])
        
        # Create another webhook for the same subscription
        webhook2 = Webhook.objects.create(
            subscription=self.subscription,
            payload={'event': 'test2', 'data': {'id': 456}},
            event_type='test.event2',
            status='DELIVERED'
        )
        
        DeliveryAttempt.objects.create(
            webhook=webhook2,
            attempt_number=1,
            status_code=200,
            error_detail='',
            is_success=True
        )
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)  # Two webhooks
        
        # Webhooks should be sorted by created_at (newest first)
        self.assertEqual(response.data[0]['id'], str(webhook2.id))
        self.assertEqual(response.data[1]['id'], str(self.webhook.id)) 
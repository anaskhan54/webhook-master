from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
import hmac
import hashlib
import json
from .models import Subscription, Webhook, DeliveryAttempt
from .serializers import (
    SubscriptionSerializer, 
    WebhookSerializer, 
    WebhookStatusSerializer,
    DeliveryAttemptSerializer
)
from django.core.cache import cache
from .tasks import process_webhook_delivery
import logging

logger = logging.getLogger(__name__)

# Subscription CRUD endpoints
class SubscriptionList(APIView):
    def get(self, request):
        """List all webhook subscriptions"""
        subscriptions = Subscription.objects.all()
        serializer = SubscriptionSerializer(subscriptions, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        """Create a new webhook subscription"""
        serializer = SubscriptionSerializer(data=request.data)
        if serializer.is_valid():
            subscription = serializer.save()
            # Cache subscription data
            cache.set(f"subscription_{subscription.id}", subscription, timeout=3600)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SubscriptionDetail(APIView):
    def get_object(self, pk):
        # Try to get from cache first
        cached_subscription = cache.get(f"subscription_{pk}")
        if cached_subscription:
            return cached_subscription
        
        # If not in cache, get from database and cache it
        subscription = get_object_or_404(Subscription, pk=pk)
        cache.set(f"subscription_{pk}", subscription, timeout=3600)
        return subscription
    
    def get(self, request, pk):
        """Get subscription details"""
        subscription = self.get_object(pk)
        serializer = SubscriptionSerializer(subscription)
        return Response(serializer.data)
    
    def put(self, request, pk):
        """Update subscription"""
        subscription = self.get_object(pk)
        serializer = SubscriptionSerializer(subscription, data=request.data)
        if serializer.is_valid():
            updated_subscription = serializer.save()
            # Update cache
            cache.set(f"subscription_{pk}", updated_subscription, timeout=3600)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """Delete subscription"""
        subscription = self.get_object(pk)
        subscription.delete()
        # Delete from cache
        cache.delete(f"subscription_{pk}")
        return Response(status=status.HTTP_204_NO_CONTENT)

# Webhook ingestion endpoint
class WebhookIngestion(APIView):
    def post(self, request, subscription_id):
        """Ingest webhook payload for a subscription"""
        try:
            # Get subscription (cached if possible)
            cached_subscription = cache.get(f"subscription_{subscription_id}")
            if cached_subscription:
                subscription = cached_subscription
            else:
                subscription = get_object_or_404(Subscription, pk=subscription_id)
                cache.set(f"subscription_{subscription_id}", subscription, timeout=3600)
            
            # Check if subscription is active
            if not subscription.is_active:
                return Response(
                    {"error": "Subscription is not active"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verify webhook signature if secret is present
            if subscription.secret_key:
                signature_header = request.headers.get('X-Hub-Signature-256', '')
                if not signature_header:
                    return Response(
                        {"error": "Missing X-Hub-Signature-256 header"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Calculate expected signature
                payload_bytes = json.dumps(request.data).encode('utf-8')
                expected_signature = hmac.new(
                    subscription.secret_key.encode('utf-8'),
                    payload_bytes,
                    hashlib.sha256
                ).hexdigest()
                expected_header = f'sha256={expected_signature}'
                
                # Compare signatures
                if not hmac.compare_digest(signature_header, expected_header):
                    return Response(
                        {"error": "Invalid signature"}, 
                        status=status.HTTP_401_UNAUTHORIZED
                    )
            
            # Get event type if provided
            event_type = request.query_params.get('event_type', '')
            
            # Check event type filtering (if enabled)
            if event_type and subscription.event_types and len(subscription.event_types) > 0:
                if event_type not in subscription.event_types:
                    return Response(
                        {"error": f"This subscription does not accept event type: {event_type}. Allowed types: {subscription.event_types}"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Create webhook
            webhook = Webhook.objects.create(
                subscription=subscription,
                payload=request.data,
                event_type=event_type,
                status='PENDING'
            )
            
            # Queue webhook delivery task (async)
            process_webhook_delivery.delay(str(webhook.id))
            
            return Response(
                {"id": str(webhook.id), "status": "accepted"},
                status=status.HTTP_202_ACCEPTED
            )
            
        except Exception as e:
            logger.exception(f"Error in webhook ingestion: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# Webhook status endpoint
class WebhookStatus(APIView):
    def get(self, request, webhook_id):
        """Get webhook delivery status and history"""
        webhook = get_object_or_404(Webhook, pk=webhook_id)
        serializer = WebhookStatusSerializer(webhook)
        return Response(serializer.data)

# Delivery history for a subscription
class DeliveryHistory(APIView):
    def get(self, request, subscription_id):
        """Get recent webhook delivery history for a subscription"""
        subscription = get_object_or_404(Subscription, pk=subscription_id)
        
        # Get recent webhooks (last 20)
        webhooks = Webhook.objects.filter(
            subscription=subscription
        ).order_by('-created_at')[:20]
        
        serializer = WebhookSerializer(webhooks, many=True)
        return Response(serializer.data)


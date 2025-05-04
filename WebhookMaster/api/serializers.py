from rest_framework import serializers
from .models import Subscription, Webhook, DeliveryAttempt

class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ['id', 'target_url', 'secret_key', 'event_types', 'created_at', 'updated_at', 'is_active']
        read_only_fields = ['id', 'created_at', 'updated_at']

class DeliveryAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryAttempt
        fields = ['id', 'webhook', 'timestamp', 'attempt_number', 'status_code', 'error_detail', 'is_success']
        read_only_fields = ['id', 'timestamp']

class WebhookSerializer(serializers.ModelSerializer):
    delivery_attempts = DeliveryAttemptSerializer(many=True, read_only=True)
    
    class Meta:
        model = Webhook
        fields = ['id', 'subscription', 'payload', 'event_type', 'created_at', 
                 'status', 'next_retry_at', 'retry_count', 'delivery_attempts']
        read_only_fields = ['id', 'created_at', 'status', 'next_retry_at', 'retry_count']

class WebhookStatusSerializer(serializers.ModelSerializer):
    delivery_attempts = DeliveryAttemptSerializer(many=True, read_only=True)
    subscription_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Webhook
        fields = ['id', 'subscription', 'subscription_url', 'payload', 'event_type', 
                 'created_at', 'status', 'next_retry_at', 'retry_count', 'delivery_attempts']
        read_only_fields = ['id', 'subscription', 'payload', 'event_type', 'created_at', 
                           'status', 'next_retry_at', 'retry_count', 'delivery_attempts']
    
    def get_subscription_url(self, obj):
        return obj.subscription.target_url

from django.contrib import admin
from .models import Subscription, Webhook, DeliveryAttempt

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'target_url', 'created_at', 'is_active')
    search_fields = ('id', 'target_url')
    list_filter = ('is_active', 'created_at')

@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ('id', 'subscription', 'event_type', 'status', 'created_at', 'retry_count')
    search_fields = ('id', 'event_type')
    list_filter = ('status', 'created_at')
    date_hierarchy = 'created_at'

@admin.register(DeliveryAttempt)
class DeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ('id', 'webhook', 'attempt_number', 'timestamp', 'status_code', 'is_success')
    search_fields = ('id', 'webhook__id')
    list_filter = ('is_success', 'timestamp')
    date_hierarchy = 'timestamp'

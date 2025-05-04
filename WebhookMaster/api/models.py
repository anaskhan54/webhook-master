from django.db import models
import uuid

class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target_url = models.URLField(max_length=500)
    secret_key = models.CharField(max_length=256, blank=True, null=True)
    event_types = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Subscription {self.id}"

class Webhook(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'), 
        ('DELIVERED', 'Delivered'),
        ('FAILED', 'Failed')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='webhooks')
    payload = models.JSONField()
    event_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    next_retry_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['subscription', '-created_at']),
            models.Index(fields=['status', 'next_retry_at']),
        ]

class DeliveryAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name='delivery_attempts')
    timestamp = models.DateTimeField(auto_now_add=True)
    attempt_number = models.IntegerField()
    status_code = models.IntegerField(null=True)
    error_detail = models.TextField(blank=True)
    is_success = models.BooleanField()

    class Meta:
        indexes = [
            models.Index(fields=['webhook', '-timestamp']),
            models.Index(fields=['-timestamp']),  # For retention cleanup
        ]



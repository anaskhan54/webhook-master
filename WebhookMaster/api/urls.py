from django.urls import path
from .views import *

urlpatterns = [
    path('subscriptions/', SubscriptionList.as_view(), name='subscription-list'),
    path('subscriptions/<str:pk>/', SubscriptionDetail.as_view(), name='subscription-detail'),
    path('ingest/<str:subscription_id>/', WebhookIngestion.as_view(), name='webhook-ingestion'),
    path('status/<str:webhook_id>/', WebhookStatus.as_view(), name='webhook-status'),
    path('subscriptions/<str:subscription_id>/history/', DeliveryHistory.as_view(), name='delivery-history'),
]

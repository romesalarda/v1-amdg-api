"""
URL configuration for payments app.

Defines API routes for all payment-related endpoints following the /list/ pattern.

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.payments.api.viewsets import (
    PaymentViewSet,
    PaymentMethodViewSet,
    DiscountViewSet,
    DiscountRuleViewSet,
    RefundRequestViewSet,
    RefundAssociationViewSet,
    RefundPolicyViewSet,
    DonationViewSet,
    PaymentHistoryActionViewSet,
)
from apps.payments.api.stripe_views import (
    StripeConfigView,
    CreatePaymentIntentView,
    StripeConfirmPaymentView,
    stripe_webhook_view,
)

app_name = 'payments'

# Initialize router
router = DefaultRouter()

# Register viewsets with /list/ pattern
router.register(r'list', PaymentViewSet, basename='payment')
router.register(r'methods', PaymentMethodViewSet, basename='paymentmethod')
router.register(r'discounts', DiscountViewSet, basename='discount')
router.register(r'discount-rules', DiscountRuleViewSet, basename='discountrule')
router.register(r'refunds', RefundRequestViewSet, basename='refundrequest')
router.register(r'refund-associations', RefundAssociationViewSet, basename='refundassociation')
router.register(r'refund-policies', RefundPolicyViewSet, basename='refundpolicy')
router.register(r'donations', DonationViewSet, basename='donation')
router.register(r'history', PaymentHistoryActionViewSet, basename='paymenthistory')

urlpatterns = [
    path('payments/', include(router.urls)),
    
    # Stripe endpoints (outside router for custom URLs)
    path('stripe/config/', StripeConfigView.as_view(), name='stripe-config'),
    path('stripe/payment-intent/', CreatePaymentIntentView.as_view(), name='stripe-create-payment-intent'),
    path('stripe/confirm/', StripeConfirmPaymentView.as_view(), name='stripe-confirm-payment'),
    path('stripe/webhook/', stripe_webhook_view, name='stripe-webhook'),
]

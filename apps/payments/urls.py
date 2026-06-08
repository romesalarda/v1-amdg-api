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
    StockAuditLogViewSet,
    CreditExpenseViewSet,
    BankTransferEvidenceViewSet,
    DebitExpenseViewSet,
    BudgetProposalViewSet,
    StripeConfigView,
    StripeConnectStatusView,
    StripeConnectOnboardingView,
    CreatePaymentIntentView,
    StripeConfirmPaymentView,
    PaymentStatisticsViewSet,
    StripeConnectedAccountViewSet,
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
router.register(r'stock-audit', StockAuditLogViewSet, basename='stockauditlog')
router.register(r'credits', CreditExpenseViewSet, basename='creditexpense')
router.register(r'bank-transfer-evidence', BankTransferEvidenceViewSet, basename='banktransferevidence')
router.register(r'debits', DebitExpenseViewSet, basename='debitexpense')
router.register(r'budget-proposals', BudgetProposalViewSet, basename='budgetproposal')

# Register statistics viewset
router.register(r'statistics', PaymentStatisticsViewSet, basename='payment-statistics')

urlpatterns = [
    path('payments/', include(router.urls)),

    # Stripe connected accounts (user-scoped)
    path(
        'stripe/connect-accounts/',
        StripeConnectedAccountViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='stripe-connect-accounts-list',
    ),
    path(
        'stripe/connect-accounts/<str:stripe_account_id>/',
        StripeConnectedAccountViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}),
        name='stripe-connect-accounts-detail',
    ),
    path(
        'stripe/connect-accounts/<str:stripe_account_id>/set-primary/',
        StripeConnectedAccountViewSet.as_view({'post': 'set_primary'}),
        name='stripe-connect-accounts-set-primary',
    ),
    
    # Stripe endpoints (outside router for custom URLs)
    path('stripe/config/', StripeConfigView.as_view(), name='stripe-config'),
    path('stripe/connect/', StripeConnectStatusView.as_view(), name='stripe-connect-status'),
    path('stripe/connect/onboard/', StripeConnectOnboardingView.as_view(), name='stripe-connect-onboard'),
    path('stripe/payment-intent/', CreatePaymentIntentView.as_view(), name='stripe-create-payment-intent'),
    path('stripe/confirm/', StripeConfirmPaymentView.as_view(), name='stripe-confirm-payment'),
    path('stripe/webhook/', stripe_webhook_view, name='stripe-webhook'),
]

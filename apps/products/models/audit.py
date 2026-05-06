"""
Audit and logging models for stock management and payment tracking.
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()
class StockAuditLog(models.Model):
    """
    Immutable audit trail for all stock changes.
    Every increment/decrement operation is logged with before/after quantities,
    reason, actor, and associated transaction IDs for full traceability.
    """
    
    class ChangeReasonChoices(models.TextChoices):
        INITIAL_ORDER_DEDUCTION = 'initial_order_deduction', 'Initial Order Deduction'
        ORDER_CANCELLATION_RESTORE = 'order_cancellation_restore', 'Order Cancellation Restore'
        PAYMENT_FAILURE_RESTORE = 'payment_failure_restore', 'Payment Failure Restore'
        REFUND_RESTORATION = 'refund_restoration', 'Refund Restoration'
        PARTIAL_REFUND_RESTORATION = 'partial_refund_restoration', 'Partial Refund Restoration'
        MANUAL_ADJUSTMENT = 'manual_adjustment', 'Manual Adjustment'
        ADMIN_ACTION = 'admin_action', 'Admin Action'
        STOCK_RESTORATION_SAFETY_NET = 'stock_restoration_safety_net', 'Stock Restoration Safety Net'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_variant = models.ForeignKey(
        'products.ProductVariant',
        on_delete=models.PROTECT,  # Never delete audit records
        related_name='stock_audit_logs'
    )
    
    # Stock quantities
    old_quantity = models.PositiveIntegerField(help_text='Stock quantity before change')
    new_quantity = models.PositiveIntegerField(help_text='Stock quantity after change')
    change_amount = models.IntegerField(help_text='Net change (positive=increment, negative=decrement)')
    
    # Reason and context
    change_reason = models.CharField(
        max_length=50,
        choices=ChangeReasonChoices.choices,
        db_index=True
    )
    
    # Transaction linkage
    order_id = models.UUIDField(null=True, blank=True, db_index=True, help_text='Associated Order UUID if applicable')
    payment_id = models.UUIDField(null=True, blank=True, db_index=True, help_text='Associated Payment UUID if applicable')
    order_item_id = models.BigIntegerField(null=True, blank=True, help_text='Associated OrderItem database ID if applicable')
    webhook_event_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text='Stripe webhook event ID for idempotency'
    )
    
    # Actor tracking
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_adjustments_made'
    )
    
    # Timestamp and audit info
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    session_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text='Session or request ID for tracing multiple related operations'
    )
    
    notes = models.TextField(blank=True, null=True, help_text='Additional context or notes')
    
    class Meta:
        verbose_name = 'Stock Audit Log'
        verbose_name_plural = 'Stock Audit Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product_variant', '-created_at']),
            models.Index(fields=['order_id', '-created_at']),
            models.Index(fields=['payment_id', '-created_at']),
            models.Index(fields=['webhook_event_id']),
        ]
    
    def __str__(self):
        direction = '+' if self.change_amount > 0 else '-'
        return f"StockAudit: {self.product_variant.id} {direction}{abs(self.change_amount)} ({self.change_reason})"
    
    def __repr__(self):
        return f"<StockAuditLog product={self.product_variant.id} change={self.change_amount} reason={self.change_reason}>"


class PaymentStockLink(models.Model):
    """
    Maps Payment → StockAuditLog entries.
    Enables quick lookup of all stock changes caused by a specific payment.
    """
    
    class LinkTypeChoices(models.TextChoices):
        INITIAL_DEDUCTION = 'initial_deduction', 'Initial Deduction (Order Created)'
        REFUND_RESTORATION = 'refund_restoration', 'Refund Restoration'
        FAILURE_ROLLBACK = 'failure_rollback', 'Failure Rollback'
        CANCELLATION_RESTORATION = 'cancellation_restoration', 'Cancellation Restoration'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_id = models.UUIDField(db_index=True, help_text='UUID of associated Payment')
    stock_audit_log = models.ForeignKey(
        StockAuditLog,
        on_delete=models.PROTECT,
        related_name='payment_links'
    )
    link_type = models.CharField(
        max_length=30,
        choices=LinkTypeChoices.choices
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Payment Stock Link'
        verbose_name_plural = 'Payment Stock Links'
        unique_together = [['payment_id', 'stock_audit_log']]
        indexes = [
            models.Index(fields=['payment_id', '-created_at']),
        ]
    
    def __str__(self):
        return f"PaymentLink: payment={self.payment_id} → stock_change={self.stock_audit_log.id}"


class WebhookEvent(models.Model):
    """
    Idempotency tracking for webhook events.
    Prevents duplicate processing of retried webhooks (e.g., Stripe retries).
    """
    
    class EventStatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text='External event ID (e.g., Stripe event_id)'
    )
    event_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Type of event (e.g., charge.failed, charge.refunded)'
    )
    status = models.CharField(
        max_length=20,
        choices=EventStatusChoices.choices,
        default=EventStatusChoices.PENDING,
        db_index=True
    )
    
    # Payload (for re-processing if needed)
    payload = models.JSONField(help_text='Complete webhook payload')
    
    # Processing info
    first_received_at = models.DateTimeField(auto_now_add=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    
    # Associated transactions
    payment_id = models.UUIDField(null=True, blank=True, db_index=True)
    order_id = models.UUIDField(null=True, blank=True, db_index=True)
    
    class Meta:
        verbose_name = 'Webhook Event'
        verbose_name_plural = 'Webhook Events'
        ordering = ['-first_received_at']
    
    def __str__(self):
        return f"WebhookEvent({self.event_type}): {self.event_id[:20]}... [{self.status}]"
    
    def mark_processing(self):
        self.status = self.EventStatusChoices.PROCESSING
        self.processing_started_at = timezone.now()
        self.save(update_fields=['status', 'processing_started_at'])
    
    def mark_completed(self):
        self.status = self.EventStatusChoices.COMPLETED
        self.processing_completed_at = timezone.now()
        self.save(update_fields=['status', 'processing_completed_at'])
    
    def mark_failed(self, error_message: str):
        self.status = self.EventStatusChoices.FAILED
        self.error_message = error_message
        self.processing_completed_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'processing_completed_at'])


class RefundRollbackLog(models.Model):
    """
    Detailed logging of refund rejections and rollback operations.
    Enables forensic analysis if rollback fails or produces unexpected results.
    """
    
    class RollbackStatusChoices(models.TextChoices):
        INITIATED = 'initiated', 'Initiated'
        VALIDATING = 'validating', 'Validating'
        VALIDATION_FAILED = 'validation_failed', 'Validation Failed'
        RESTORING = 'restoring', 'Restoring'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    payment_id = models.UUIDField(db_index=True)
    
    status = models.CharField(
        max_length=20,
        choices=RollbackStatusChoices.choices,
        default=RollbackStatusChoices.INITIATED,
        db_index=True
    )
    
    # Snapshot validation
    snapshot_before = models.JSONField(help_text='Order state snapshot before rollback')
    snapshot_after = models.JSONField(null=True, blank=True, help_text='Order state snapshot after rollback')
    validation_issues = models.JSONField(
        default=list,
        blank=True,
        help_text='List of validation issues found in snapshot'
    )
    
    # Error tracking
    error_message = models.TextField(blank=True, null=True)
    error_traceback = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Actor
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='refund_rollbacks_initiated'
    )
    
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name = 'Refund Rollback Log'
        verbose_name_plural = 'Refund Rollback Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_id', '-created_at']),
            models.Index(fields=['payment_id', '-created_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"RollbackLog(order={self.order_id}, payment={self.payment_id}): {self.status}"

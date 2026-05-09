"""Services for attendee pre-removal validation and blocker summaries."""

from collections import OrderedDict

from django.core.paginator import Paginator
from django.db.models import Q

from apps.attendee.api.serializers import AttendeePreRemovalSummarySerializer


class AttendeePreRemovalSummaryService:
	"""Build and validate attendee pre-removal summaries."""

	def __init__(self, *, request=None):
		self.request = request

	def build_summary(self, attendee):
		"""Build a validated pre-removal summary payload."""
		from apps.bookings.models import Ticket, TicketStatusChoices
		from apps.payments.models import PaymentStatusChoices
		from apps.products.models import Order, OrderStatusChoices

		blockers = []
		summary_counts = {
			'linked_payments': 0,
			'outstanding_payments': 0,
			'active_refund_requests': 0,
			'active_tickets': 0,
			'unresolved_orders': 0,
			'open_attendance': 0,
			'family_memberships': 0,
			'total_blockers': 0,
			'high_priority_blockers': 0,
			'medium_priority_blockers': 0,
		}

		linked_payments = self.get_linked_payments(attendee)

		non_blocking_payment_statuses = [
			PaymentStatusChoices.REFUNDED,
			PaymentStatusChoices.CANCELLED,
			PaymentStatusChoices.FAILED,
		]
		blocking_payments = linked_payments.exclude(status__in=non_blocking_payment_statuses)
		summary_counts['linked_payments'] = blocking_payments.count()

		outstanding_payments = blocking_payments.filter(
			status__in=[
				PaymentStatusChoices.DRAFTING,
				PaymentStatusChoices.PENDING,
				# PaymentStatusChoices.COMPLETED,
				# PaymentStatusChoices.PENDING_REFUND,
				# PaymentStatusChoices.PARTIALLY_REFUNDED,
			]
		)
		summary_counts['outstanding_payments'] = outstanding_payments.count()
		if outstanding_payments.exists():
			items, pagination = self._paginate_items(
				[self._build_payment_item(payment) for payment in outstanding_payments]
			)
			blockers.append(
				{
					'code': 'outstanding_payments',
					'severity': 'high',
					'count': outstanding_payments.count(),
					'message': 'Attendee has outstanding payments that must be resolved before deletion.',
					'items': items,
					'pagination': pagination,
					'action_hint': 'Review each payment and request a refund if applicable.',
				}
			)

		if blocking_payments.exists():
			items, pagination = self._paginate_items(
				[self._build_payment_item(payment) for payment in blocking_payments]
			)
			if items:
				blockers.append(
					{
						'code': 'linked_payments',
						'severity': 'high',
						'count': blocking_payments.count(),
						'message': 'Attendee has linked payment history that may require review before deletion.',
						'items': items,
						'pagination': pagination,
						'action_hint': 'Review each payment and request a refund from the specific payment row when eligible.',
					}
				)

		active_tickets = Ticket.objects.filter(
			attendee=attendee,
			status=TicketStatusChoices.ACTIVE,
		).select_related('ticket_type', 'payment__method')
		summary_counts['active_tickets'] = active_tickets.count()
		if active_tickets.exists():
			items, pagination = self._paginate_items(
				[self._build_ticket_item(ticket) for ticket in active_tickets]
			)
			blockers.append(
				{
					'code': 'active_tickets',
					'severity': 'high',
					'count': active_tickets.count(),
					'message': 'Attendee has active tickets that must be cancelled before deletion.',
					'items': items,
					'pagination': pagination,
					'action_hint': 'Cancel or invalidate all active tickets before removing this attendee.',
				}
			)

		linked_orders = Order.objects.filter(attendee=attendee).exclude(
			status__in=[OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED]
		).select_related('payment__method')
		summary_counts['unresolved_orders'] = linked_orders.count()
		if linked_orders.exists():
			items, pagination = self._paginate_items(
				[self._build_order_item(order) for order in linked_orders]
			)
			blockers.append(
				{
					'code': 'unresolved_orders',
					'severity': 'medium',
					'count': linked_orders.count(),
					'message': 'Attendee has linked orders that may require review before deletion.',
					'items': items,
					'pagination': pagination,
					'action_hint': 'Review each order and ensure it is in a final state before removing this attendee.',
				}
			)

		payments_with_active_refunds = blocking_payments.filter(
			refund_requests__is_active=True,
		).distinct()
		summary_counts['active_refund_requests'] = payments_with_active_refunds.count()
		if payments_with_active_refunds.exists():
			items, pagination = self._paginate_items(
				[self._build_payment_item(payment) for payment in payments_with_active_refunds]
			)
			blockers.append(
				{
					'code': 'active_refunds',
					'severity': 'medium',
					'count': payments_with_active_refunds.count(),
					'message': 'Attendee has payments with active refund requests that must be resolved before deletion.',
					'items': items,
					'pagination': pagination,
					'action_hint': 'Resolve all pending refund requests before removing this attendee.',
				}
			)

		summary_counts['total_blockers'] = len(blockers)
		summary_counts['high_priority_blockers'] = len(
			[blocker for blocker in blockers if blocker['severity'] in {'critical', 'high'}]
		)
		summary_counts['medium_priority_blockers'] = len(
			[blocker for blocker in blockers if blocker['severity'] == 'medium']
		)

		suggested_actions = self._build_suggested_actions(blockers)

		payload = {
			'attendee': {
				'attendee_id': str(attendee.attendee_id),
				'attendee_display_id': attendee.attendee_display_id,
				'full_name': attendee.full_name,
			},
			'can_delete': len(blockers) == 0,
			'blockers': blockers,
			'summary_counts': summary_counts,
			'suggested_actions': suggested_actions,
		}
		return self._validate_summary(payload)

	def is_payment_linked_to_attendee(self, attendee, payment):
		return self.get_linked_payments(attendee).filter(id=payment.id).exists()

	def get_linked_payments(self, attendee):
		"""Get payments linked to attendee via booking, tickets, or orders."""
		from django.contrib.contenttypes.models import ContentType
		from apps.bookings.models import Booking
		from apps.payments.models import Payment

		booking_payment_ids = []
		if attendee.booking_id:
			booking_ct = ContentType.objects.get_for_model(Booking)
			booking_payment_ids = Payment.objects.filter(
				target_type=booking_ct,
				target_id=str(attendee.booking_id),
			).values_list('id', flat=True)

		ticket_payment_ids = attendee.tickets.exclude(payment__isnull=True).values_list('payment_id', flat=True)
		order_payment_ids = attendee.orders.exclude(payment__isnull=True).values_list('payment_id', flat=True)

		return Payment.objects.filter(
			Q(id__in=booking_payment_ids)
			| Q(id__in=ticket_payment_ids)
			| Q(id__in=order_payment_ids)
		).select_related('event', 'user').distinct()

	def _build_payment_item(self, payment):
		item = OrderedDict()
		item['type'] = 'payment'
		item.update(self._payment_context(payment))
		return item

	def _build_ticket_item(self, ticket):
		item = OrderedDict()
		item['type'] = 'ticket'
		item['ticket_id'] = str(ticket.ticket_id)
		item['ticket_code'] = ticket.ticket_code
		item['ticket_type'] = ticket.ticket_type.title if ticket.ticket_type else None
		item['ticket_scope'] = ticket.ticket_type.scope if ticket.ticket_type else None
		item['status'] = ticket.status
		if ticket.payment:
			item.update(self._payment_context(ticket.payment))
		return item

	def _build_order_item(self, order):
		item = OrderedDict()
		item['type'] = 'order'
		item['order_id'] = str(order.order_id)
		item['order_reference'] = order.order_reference_id
		item['order_amount'] = str(order.total_amount)
		item['order_attendee_id'] = str(order.attendee.attendee_id) if order.attendee else None
		item['order_attendee_name'] = order.attendee.full_name if order.attendee else None
		item['status'] = order.status
		if order.payment:
			item.update(self._payment_context(order.payment))
		return item

	def _payment_context(self, payment):
		payment_type = self._get_payment_type(payment)
		can_request_refund, refund_block_reason = self._can_request_attendee_refund(payment)

		context = OrderedDict()
		context['payment_id'] = str(payment.payment_id)
		context['payment_reference'] = payment.payment_reference
		context['payment_type'] = payment_type
		context['payment_descriptor'] = self._get_payment_descriptor(payment_type)
		context['payment_status'] = payment.status
		context['payment_status_bucket'] = self._get_payment_status_bucket(payment.status)
		context['amount'] = str(payment.base_amount) if payment.base_amount else None
		context['currency'] = payment.base_amount.currency.code if payment.base_amount else None
		context['method_type'] = payment.method.method_type if payment.method else None
		context['method_title'] = payment.method.title if payment.method else None
		context['can_request_refund'] = can_request_refund
		context['refund_block_reason'] = refund_block_reason

		if payment.target_type and payment.target and payment_type == 'booking':
			booking = payment.target
			context['booking_id'] = str(booking.id)
			context['booking_reference'] = booking.booking_reference
			context['booking_attendee_count'] = booking.attendees.filter(deleted_at__isnull=True).count()

		return context

	def _get_page_and_page_size(self):
		query_params = getattr(self.request, 'query_params', None) or getattr(self.request, 'GET', {}) or {}

		try:
			page = int(query_params.get('page', 1) or 1)
		except (TypeError, ValueError):
			page = 1

		default_size = 20
		max_size = 100
		page_size_key = 'page_size'

		try:
			page_size = int(query_params.get(page_size_key, default_size) or default_size)
		except (TypeError, ValueError):
			page_size = default_size

		page = max(page, 1)
		page_size = min(max(page_size, 1), max_size)
		return page, page_size

	def _paginate_items(self, items):
		page, page_size = self._get_page_and_page_size()
		paginator = Paginator(items, page_size)
		page_obj = paginator.get_page(page)
		return list(page_obj.object_list), {
			'count': paginator.count,
			'page': page_obj.number,
			'page_size': page_size,
			'total_pages': paginator.num_pages,
			'has_next': page_obj.has_next(),
			'has_previous': page_obj.has_previous(),
			'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
			'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
		}

	def _validate_summary(self, payload):
		serializer = AttendeePreRemovalSummarySerializer(data=payload)
		serializer.is_valid(raise_exception=True)
		return serializer.validated_data

	def _build_suggested_actions(self, blockers):
		suggestions = []
		blocker_codes = {blocker['code'] for blocker in blockers}

		if 'outstanding_payments' in blocker_codes:
			suggestions.append(
				{
					'code': 'review_outstanding_payments',
					'message': 'Review outstanding payments and submit refunds where eligible.',
				}
			)
		if 'active_tickets' in blocker_codes:
			suggestions.append(
				{
					'code': 'cancel_active_tickets',
					'message': 'Cancel or invalidate all active tickets for this attendee.',
				}
			)
		if 'unresolved_orders' in blocker_codes:
			suggestions.append(
				{
					'code': 'finalize_orders',
					'message': 'Move unresolved orders to a final state before deleting the attendee.',
				}
			)
		if 'active_refunds' in blocker_codes:
			suggestions.append(
				{
					'code': 'resolve_active_refunds',
					'message': 'Wait for active refund requests to complete before deletion.',
				}
			)

		return suggestions

	def _get_payment_type(self, payment):
		if payment.target_type:
			target_model = payment.target_type.model.lower()
			if target_model == 'eventsponsor':
				return 'sponsorship'
			return {
				'booking': 'booking',
				'order': 'order',
				'ticket': 'ticket',
			}.get(target_model, target_model)

		metadata = payment.metadata if isinstance(payment.metadata, dict) else {}
		payment_type = str(metadata.get('payment_type') or '').lower()
		if 'booking' in payment_type:
			return 'booking'
		if 'order' in payment_type:
			return 'order'
		if 'ticket' in payment_type:
			return 'ticket'
		if 'donation' in payment_type:
			return 'donation'
		if 'sponsor' in payment_type:
			return 'sponsorship'
		return 'unknown'

	def _get_payment_descriptor(self, payment_type):
		return {
			'booking': 'Booking Payment',
			'order': 'Order Payment',
			'ticket': 'Ticket Payment',
			'donation': 'Donation Payment',
			'sponsorship': 'Sponsorship Payment',
		}.get(payment_type, 'Payment')

	def _get_payment_status_bucket(self, status):
		return {
			'DRAFTING': 'in_flight',
			'PENDING': 'outstanding',
			'COMPLETED': 'settled',
			'PENDING_REFUND': 'refund_pending',
			'REFUNDED': 'refunded',
			'PARTIALLY_REFUNDED': 'partially_refunded',
			'CANCELLED': 'cancelled',
			'FAILED': 'failed',
		}.get(status, 'unknown')

	def _can_request_attendee_refund(self, payment):
		from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
		from apps.payments.models import PaymentStatusChoices

		user = getattr(self.request, 'user', None)
		if not user or user.is_anonymous:
			return False, 'Sign in as an eligible user to request this refund.'

		if payment.status != PaymentStatusChoices.COMPLETED:
			return False, 'Refund requests can only be created for completed payments.'

		if payment.refund_requests.filter(is_active=True).exists():
			return False, 'This payment already has an active refund request.'

		is_event_admin = EventRoleAssignment.objects.filter(
			user=user,
			event=payment.event,
			role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
		).exists()
		if user.is_superuser or user.is_staff or payment.user_id == user.id or is_event_admin:
			return True, None

		return False, 'You do not have permission to request this attendee refund.'

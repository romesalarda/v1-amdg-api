"""
Test factories for creating consistent test data across the application.

Uses factory_boy to generate realistic model instances for testing.
"""
import factory
from factory.django import DjangoModelFactory
from factory import fuzzy
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
import uuid

User = get_user_model()


class UserFactory(DjangoModelFactory):
    """Factory for creating User instances."""
    
    class Meta:
        model = User
        django_get_or_create = ('email',)
    
    email = factory.Sequence(lambda n: f'testuser{n}@example.com')
    username = factory.Sequence(lambda n: f'testuser{n}')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    is_active = True
    is_staff = False
    is_superuser = False


class EventTypeFactory(DjangoModelFactory):
    """Factory for creating EventType instances."""
    
    class Meta:
        model = 'events.EventType'
        django_get_or_create = ('code',)
    
    title = factory.Sequence(lambda n: f'Event Type {n}')
    code = factory.Sequence(lambda n: f'ET{n}')
    description = factory.Faker('sentence')
    created_by = factory.SubFactory(UserFactory)


class OrganisationFactory(DjangoModelFactory):
    """Factory for creating Organisation instances."""
    
    class Meta:
        model = 'organisations.Organisation'
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Organisation {n}')
    description = factory.Faker('text')
    created_by = factory.SubFactory(UserFactory)


class EventFactory(DjangoModelFactory):
    """Factory for creating Event instances."""
    
    class Meta:
        model = 'events.Event'
    
    event_id = factory.LazyFunction(uuid.uuid4)
    display_code = factory.Sequence(lambda n: f'EV{n:03d}')
    title = factory.Sequence(lambda n: f'Test Event {n}')
    short_description = factory.Faker('sentence')
    long_description = factory.Faker('text')
    status = 'OPEN'
    event_type = factory.SubFactory(EventTypeFactory)
    organisation = factory.SubFactory(OrganisationFactory)
    created_by = factory.SubFactory(UserFactory)
    timezone = 'Europe/London'
    
    start_datetime = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=30))
    end_datetime = factory.LazyAttribute(lambda obj: obj.start_datetime + timezone.timedelta(days=3))
    
    expected_attendance = 100
    maximum_attendance = 150


class EventSettingsFactory(DjangoModelFactory):
    """Factory for creating EventSettings instances."""
    
    class Meta:
        model = 'events.EventSettings'
    
    event = factory.SubFactory(EventFactory)
    payment_enabled = True
    products_require_approval = False
    product_publication_requires_verification = False
    product_selling_enabled = True
    orders_require_approval = True
    donation_enabled = True
    refunds_enabled = True
    accepting_sponsorships_enabled = False
    participants_registration_require_verification = False


class AttendeeFactory(DjangoModelFactory):
    """Factory for creating Attendee instances."""
    
    class Meta:
        model = 'attendee.Attendee'
    
    attendee_id = factory.LazyFunction(uuid.uuid4)
    event = factory.SubFactory(EventFactory)
    user = factory.SubFactory(UserFactory)
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    email = factory.Faker('email')
    phone_number = factory.Faker('phone_number')
    date_of_birth = factory.Faker('date_of_birth', minimum_age=18, maximum_age=80)


class TicketTypeFactory(DjangoModelFactory):
    """Factory for creating TicketType instances."""
    
    class Meta:
        model = 'bookings.TicketType'
    
    title = factory.Sequence(lambda n: f'Ticket Type {n}')
    code = factory.Sequence(lambda n: f'TT{n}')
    event = factory.SubFactory(EventFactory)
    base_price = Decimal('50.00')
    base_price_currency = 'GBP'


class BookingPackageFactory(DjangoModelFactory):
    """Factory for creating BookingPackage instances."""
    
    class Meta:
        model = 'bookings.BookingPackage'
    
    name = factory.Sequence(lambda n: f'Package {n}')
    description = factory.Faker('sentence')
    event = factory.SubFactory(EventFactory)
    ticket_type = factory.SubFactory(TicketTypeFactory)
    base_price = Decimal('100.00')
    base_price_currency = 'GBP'
    is_active = True
    created_by = factory.SubFactory(UserFactory)


class BookingFactory(DjangoModelFactory):
    """Factory for creating Booking instances."""
    
    class Meta:
        model = 'bookings.Booking'
    
    event = factory.SubFactory(EventFactory)
    booking_reference = factory.Sequence(lambda n: f'BK-TEST-{n:06d}')
    made_by = factory.SubFactory(UserFactory)


class PaymentMethodFactory(DjangoModelFactory):
    """Factory for creating PaymentMethod instances."""
    
    class Meta:
        model = 'payments.PaymentMethod'
    
    method_type = 'CARD'
    provider = 'STRIPE'
    is_active = True
    display_name = 'Credit/Debit Card'


class PaymentFactory(DjangoModelFactory):
    """Factory for creating Payment instances."""
    
    class Meta:
        model = 'payments.Payment'
    
    payment_reference = factory.Sequence(lambda n: f'PAY-TEST-{n:08d}')
    status = 'PENDING'
    method = factory.SubFactory(PaymentMethodFactory)
    total_amount = Decimal('100.00')
    total_amount_currency = 'GBP'
    created_by = factory.SubFactory(UserFactory)
    metadata = factory.Dict({})
    
    # Generic foreign key fields - set manually in tests
    target_type = None
    target_id = None


class ProductVariantFactory(DjangoModelFactory):
    """Factory for creating ProductVariant instances."""
    
    class Meta:
        model = 'products.ProductVariant'
    
    variant_id = factory.LazyFunction(uuid.uuid4)
    sku = factory.Sequence(lambda n: f'SKU-{n:06d}')
    price = Decimal('25.00')
    price_currency = 'GBP'
    stock = 100
    is_active = True


class OrderFactory(DjangoModelFactory):
    """Factory for creating Order instances."""
    
    class Meta:
        model = 'products.Order'
    
    order_id = factory.LazyFunction(uuid.uuid4)
    order_reference_id = factory.Sequence(lambda n: f'ORD-TEST-{n:06d}')
    customer = factory.SubFactory(UserFactory)
    attendee = factory.SubFactory(AttendeeFactory)
    status = 'draft'
    total_amount = Decimal('0.00')
    total_amount_currency = 'GBP'
    created_by = factory.SubFactory(UserFactory)


class OrderItemFactory(DjangoModelFactory):
    """Factory for creating OrderItem instances."""
    
    class Meta:
        model = 'products.OrderItem'
    
    order = factory.SubFactory(OrderFactory)
    product_variant = factory.SubFactory(ProductVariantFactory)
    quantity = 1
    unit_price = Decimal('25.00')
    unit_price_currency = 'GBP'
    total_price = factory.LazyAttribute(lambda obj: obj.quantity * obj.unit_price)
    total_price_currency = 'GBP'


class TicketFactory(DjangoModelFactory):
    """Factory for creating Ticket instances."""
    
    class Meta:
        model = 'bookings.Ticket'
    
    ticket_id = factory.LazyFunction(uuid.uuid4)
    attendee = factory.SubFactory(AttendeeFactory)
    ticket_type = factory.SubFactory(TicketTypeFactory)
    package = factory.SubFactory(BookingPackageFactory)
    status = 'ACTIVE'
    booking = factory.SubFactory(BookingFactory)


class EventNotificationFactory(DjangoModelFactory):
    """Factory for creating EventNotification instances."""
    
    class Meta:
        model = 'events.EventNotification'
    
    event = factory.SubFactory(EventFactory)
    notification_type = 'GENERAL'
    priority = 'NORMAL'
    is_read = False
    metadata = factory.Dict({})
    created_by = factory.SubFactory(UserFactory)


# Helper functions for common test scenarios

def create_booking_with_payment(
    event=None,
    user=None,
    status='COMPLETED',
    amount=Decimal('100.00')
):
    """
    Create a complete booking with associated payment.
    
    Args:
        event: Event instance (creates new if None)
        user: User instance (creates new if None)
        status: Payment status
        amount: Payment amount
    
    Returns:
        Tuple of (booking, payment)
    """
    from django.contrib.contenttypes.models import ContentType
    from apps.bookings.models import Booking
    
    if not event:
        event = EventFactory()
    if not user:
        user = UserFactory()
    
    booking = BookingFactory(event=event, made_by=user)
    
    payment = PaymentFactory(
        status=status,
        total_amount=amount,
        created_by=user,
        target_type=ContentType.objects.get_for_model(Booking),
        target_id=booking.id
    )
    
    return booking, payment


def create_order_with_payment(
    event=None,
    user=None,
    attendee=None,
    status='COMPLETED',
    amount=Decimal('50.00')
):
    """
    Create a complete order with associated payment.
    
    Args:
        event: Event instance (creates new if None)
        user: User instance (creates new if None)
        attendee: Attendee instance (creates new if None)
        status: Payment status
        amount: Payment amount
    
    Returns:
        Tuple of (order, payment)
    """
    from django.contrib.contenttypes.models import ContentType
    from apps.products.models import Order
    
    if not event:
        event = EventFactory()
    if not user:
        user = UserFactory()
    if not attendee:
        attendee = AttendeeFactory(event=event, user=user)
    
    order = OrderFactory(
        customer=user,
        attendee=attendee,
        status='pending',
        total_amount=amount,
        created_by=user
    )
    
    payment = PaymentFactory(
        status=status,
        total_amount=amount,
        created_by=user,
        target_type=ContentType.objects.get_for_model(Order),
        target_id=order.id
    )
    
    return order, payment


def create_booking_with_package_and_products(
    event=None,
    user=None,
    include_products=True
):
    """
    Create a booking with package that includes products.
    
    Args:
        event: Event instance (creates new if None)
        user: User instance (creates new if None)
        include_products: Whether to create associated order with products
    
    Returns:
        Dict with booking, package, order (if include_products), payment
    """
    from django.contrib.contenttypes.models import ContentType
    from apps.bookings.models import Booking
    
    if not event:
        event = EventFactory()
    if not user:
        user = UserFactory()
    
    # Create package
    package = BookingPackageFactory(event=event)
    
    # Create booking
    booking = BookingFactory(event=event, made_by=user)
    
    # Create attendee and ticket
    attendee = AttendeeFactory(event=event, user=user)
    ticket = TicketFactory(
        attendee=attendee,
        ticket_type=package.ticket_type,
        package=package,
        booking=booking
    )
    
    result = {
        'event': event,
        'user': user,
        'booking': booking,
        'package': package,
        'attendee': attendee,
        'ticket': ticket,
    }
    
    if include_products:
        # Create order linked to package
        order = OrderFactory(
            customer=user,
            attendee=attendee,
            booking_package=package,
            status='pending',
            total_amount=Decimal('25.00'),
            created_by=user
        )
        
        # Add product item
        variant = ProductVariantFactory()
        item = OrderItemFactory(
            order=order,
            product_variant=variant,
            quantity=1,
            unit_price=variant.price
        )
        
        result['order'] = order
        result['order_item'] = item
        result['variant'] = variant
    
    # Create payment for booking
    payment = PaymentFactory(
        status='COMPLETED',
        total_amount=Decimal('100.00'),
        created_by=user,
        target_type=ContentType.objects.get_for_model(Booking),
        target_id=booking.id,
        metadata={
            'attendee_selections': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': package.id,
                }
            ]
        }
    )
    
    result['payment'] = payment
    
    return result

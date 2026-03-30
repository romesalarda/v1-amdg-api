from django.db import migrations, models
from django.db.models import Q


def deduplicate_open_orders(apps, schema_editor):
    Order = apps.get_model('products', 'Order')
    OrderItem = apps.get_model('products', 'OrderItem')
    ProductVariant = apps.get_model('products', 'ProductVariant')

    open_statuses = ('draft', 'pending')

    attendee_ids = (
        Order.objects.filter(attendee_id__isnull=False, status__in=open_statuses)
        .values_list('attendee_id', flat=True)
        .distinct()
    )

    for attendee_id in attendee_ids:
        open_orders = list(
            Order.objects.filter(attendee_id=attendee_id, status__in=open_statuses)
            .order_by('-updated_at', '-created_at', '-id')
        )
        if len(open_orders) <= 1:
            continue

        keep_order = open_orders[0]
        for stale_order in open_orders[1:]:
            order_items = OrderItem.objects.filter(order_id=stale_order.id, product_variant_id__isnull=False)
            for item in order_items:
                ProductVariant.objects.filter(id=item.product_variant_id).update(
                    stock_quantity=models.F('stock_quantity') + item.quantity
                )

            stale_order.status = 'cancelled'
            stale_order.save(update_fields=['status', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0011_order_booking_package_orderitem_package_product'),
    ]

    operations = [
        migrations.RunPython(deduplicate_open_orders, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='order',
            constraint=models.UniqueConstraint(
                fields=('attendee',),
                condition=Q(attendee__isnull=False, status__in=('draft', 'pending')),
                name='unique_open_order_per_attendee',
            ),
        ),
    ]

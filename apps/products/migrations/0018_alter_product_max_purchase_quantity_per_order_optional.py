from django.db import migrations, models


def backfill_product_max_purchase_quantity_to_null(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    Product.objects.all().update(max_purchase_quantity_per_order=None)


def reverse_backfill_product_max_purchase_quantity_to_default(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    Product.objects.filter(max_purchase_quantity_per_order__isnull=True).update(max_purchase_quantity_per_order=5)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0017_product_max_purchase_quantity_per_order'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='max_purchase_quantity_per_order',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(
            backfill_product_max_purchase_quantity_to_null,
            reverse_backfill_product_max_purchase_quantity_to_default,
        ),
    ]

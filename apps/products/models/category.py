from django.db import models
from django.utils.translation import gettext_lazy as _
import uuid

class ProductCategory(models.Model):

    name = models.CharField(max_length=255, unique=True, verbose_name=_("Category Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Category")
        verbose_name_plural = _("Categories")
        ordering = ['name']

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<ProductCategory(name={self.name})>"
    
class EventProductCategory(models.Model): # through model linking events and product categories
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='product_categories', verbose_name=_("Event"))
    category = models.ForeignKey(ProductCategory, on_delete=models.CASCADE, related_name='event_categories', verbose_name=_("Product Category"))
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='event_product_categories', verbose_name=_("Product"), null=True, blank=True)

    added_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Added At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Event Product Category")
        verbose_name_plural = _("Event Product Categories")
        unique_together = ('event', 'category', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.event} - {self.category}"
    
    def __repr__(self):
        return f"<EventProductCategory(event={self.event}, category={self.category})>"
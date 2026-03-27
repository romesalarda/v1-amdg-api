"""
Checkout Preview Calculation Service

Handles safe calculation of checkout totals without persistence to the database.

This service is responsible for:
1. Calculating total amounts for checkout previews
2. Validating package pricing and eligibility
3. Computing product variant costs
4. Ensuring calculations match intent
5. Rollback of any test operations

Uses database savepoints to ensure no data is committed during calculations.
This makes it safe to use for preview endpoints without side effects.
"""
import logging
from typing import Dict, List, Any

from django.db import transaction
from djmoney.money import Money

from apps.attendee.models import Attendee
from apps.bookings.models import BookingIntent, BookingPackage
from apps.users.models import CommunityUser
logger = logging.getLogger(__name__)


class PreviewCalculationError(Exception):
    """Raised when preview calculation fails."""
    pass


class CheckoutPreviewCalculationService:
    """
    Service for calculating checkout totals and previewing prices.
    
    All operations are transactional with savepoints - no data is persisted.
    Safe to call for API previews and frontend calculations.
    
    Key methods:
    - calculate_checkout_total: Calculate full checkout total with all products
    - calculate_package_total: Calculate just the package price for an attendee
    - validate_pricing: Ensure calculated total matches provided total
    """
    
    @staticmethod
    def calculate_checkout_total(
        intent: BookingIntent,
        attendee_selections: List[Dict[str, Any]],
        user: CommunityUser
    ) -> Money:
        """
        Calculate checkout total from attendee selections.
        
        Calculates the complete checkout amount including:
        - All attendee package selections
        - All product variant selections
        - Contextual pricing (based on attendee eligibility, pricing rules, etc)
        
        Operations are scoped to a savepoint - nothing is persisted.
        
        Args:
            intent: BookingIntent instance
            attendee_selections: List of attendee selection dicts
            user: User making the booking (for pricing context)
            
        Returns:
            Money object with total amount
            
        Raises:
            PreviewCalculationError if calculation fails
        """
        total_amount = Money(0, 'GBP')
        savepoint = transaction.savepoint()
        
        try:
            for selection in attendee_selections:
                attendee = selection.get('_attendee')
                draft = selection.get('_attendee_draft') or {}
                package = selection.get('_package')
                product_selections = selection.get('product_selections', [])
                
                if not attendee and draft:
                    # Create temporary attendee for pricing (will be rolled back)
                    relationship = draft.get('relationship_to_user')
                    attendee_user = user if relationship == 'self' else None
                    attendee = Attendee.objects.create(
                        event=intent.event,
                        user=attendee_user,
                        defined_by=user,
                        first_name=draft.get('first_name', 'Temp'),
                        last_name=draft.get('last_name', 'Attendee'),
                        date_of_birth=draft.get('date_of_birth'),
                        email=draft.get('email') or None,
                        phone_number=draft.get('phone_number') or None,
                        gender=draft.get('gender') or None,
                        relationship_to_user=relationship or 'other',
                        area_from_id=draft.get('area_from'),
                    )
                
                if not attendee or not package:
                    raise PreviewCalculationError('Missing attendee or package in selection')
                
                # Calculate package price
                attendee_context = attendee.pricing_context()
                package_price = package.total_amount_for_context(attendee_context)
                total_amount += package_price
                
                # Calculate product prices
                if product_selections:
                    for prod_selection in product_selections:
                        package_product = prod_selection.get('_package_product')
                        variant = prod_selection.get('_variant')
                        quantity = int(prod_selection.get('quantity', 1))
                        
                        if not package_product or not variant:
                            raise PreviewCalculationError(
                                'Missing package_product or variant in product selection'
                            )
                        
                        line_total = package_product.total_amount_with_variant(
                            variant=variant,
                            context=attendee_context,
                        ) * quantity
                        total_amount += line_total
            
            return total_amount
            
        except Exception as exc:
            logger.error(f"Preview calculation failed: {str(exc)}", exc_info=True)
            raise PreviewCalculationError(str(exc)) from exc
        finally:
            # Always rollback to savepoint to prevent any persistence
            transaction.savepoint_rollback(savepoint)
    
    @staticmethod
    def calculate_package_total(
        package: BookingPackage,
        attendee: Attendee
    ) -> Money:
        """
        Calculate the total price for a package for a specific attendee.
        
        Accounts for:
        - Attendee age-based pricing rules
        - Attendee eligibility rules
        - Discount rules
        - Base package price
        
        Args:
            package: BookingPackage instance
            attendee: Attendee instance (used for pricing context)
            
        Returns:
            Money object with package total
            
        Raises:
            PreviewCalculationError if calculation fails
        """
        try:
            attendee_context = attendee.pricing_context()
            total = package.total_amount_for_context(attendee_context)
            return total
        except Exception as exc:
            raise PreviewCalculationError(
                f"Failed to calculate package total: {str(exc)}"
            ) from exc
    
    @staticmethod
    def validate_pricing(
        calculated_total: Money,
        provided_total: Money,
        tolerance: Money = None
    ) -> bool:
        """
        Validate that calculated total matches provided total (within tolerance).
        
        Args:
            calculated_total: Total calculated by this service
            provided_total: Total provided by client/payment
            tolerance: Optional tolerance (defaults to 0.01 GBP = 1p)
            
        Returns:
            True if totals match within tolerance
            
        Raises:
            PreviewCalculationError if mismatch exceeds tolerance
        """
        if tolerance is None:
            tolerance = Money('0.01', 'GBP')
        
        diff = abs(calculated_total.amount - provided_total.amount)
        
        if diff > tolerance.amount:
            raise PreviewCalculationError(
                f'Price mismatch: calculated {calculated_total}, '
                f'but received {provided_total}. Difference: {diff}'
            )
        
        return True
    
    @staticmethod
    def preview_checkout_for_display(
        intent: BookingIntent,
        attendee_selections: List[Dict[str, Any]],
        user: CommunityUser
    ) -> Dict[str, Any]:
        """
        Generate a complete checkout preview for frontend display.
        
        Returns structured data showing:
        - Total checkout amount
        - Per-attendee breakdown
        - Product selections with prices
        - Tax/discount details if applicable
        
        Args:
            intent: BookingIntent instance
            attendee_selections: List of attendee selection dicts
            user: User making the booking
            
        Returns:
            Dictionary with preview data structure
            
        Raises:
            PreviewCalculationError if preview generation fails
        """
        savepoint = transaction.savepoint()
        
        try:
            attendee_previews = []
            total_before_discount = Money(0, 'GBP')
            total_discount = Money(0, 'GBP')
            
            for selection_idx, selection in enumerate(attendee_selections):
                attendee = selection.get('_attendee')
                draft = selection.get('_attendee_draft') or {}
                package = selection.get('_package')
                product_selections = selection.get('product_selections', [])
                
                if not attendee and draft:
                    relationship = draft.get('relationship_to_user')
                    attendee_user = user if relationship == 'self' else None
                    attendee = Attendee.objects.create(
                        event=intent.event,
                        user=attendee_user,
                        defined_by=user,
                        first_name=draft.get('first_name', 'Attendee'),
                        last_name=draft.get('last_name', str(selection_idx + 1)),
                        date_of_birth=draft.get('date_of_birth'),
                        email=draft.get('email') or None,
                        phone_number=draft.get('phone_number') or None,
                        gender=draft.get('gender') or None,
                        relationship_to_user=relationship or 'other',
                        area_from_id=draft.get('area_from'),
                    )
                
                if not attendee or not package:
                    continue
                
                attendee_name = f"{attendee.first_name} {attendee.last_name}"
                attendee_context = attendee.pricing_context()
                
                # Calculate package price
                package_price = package.total_amount_for_context(attendee_context)
                total_before_discount += package_price
                
                product_previews = []
                attendee_product_total = Money(0, 'GBP')
                
                # Calculate product prices
                if product_selections:
                    for prod_selection in product_selections:
                        package_product = prod_selection.get('_package_product')
                        variant = prod_selection.get('_variant')
                        quantity = int(prod_selection.get('quantity', 1))
                        
                        if not package_product or not variant:
                            continue
                        
                        line_price = package_product.total_amount_with_variant(
                            variant=variant,
                            context=attendee_context,
                        )
                        line_total = line_price * quantity
                        attendee_product_total += line_total
                        total_before_discount += line_total
                        
                        product_previews.append({
                            'package_product_id': package_product.id,
                            'product_name': package_product.product.title,
                            'variant_name': variant.name,
                            'quantity': quantity,
                            'unit_price': str(line_price.amount),
                            'line_total': str(line_total.amount),
                            'currency': line_total.currency.code,
                        })
                
                attendee_total = package_price + attendee_product_total
                
                attendee_previews.append({
                    'index': selection_idx,
                    'name': attendee_name,
                    'package_name': package.name,
                    'package_price': str(package_price.amount),
                    'products': product_previews,
                    'product_total': str(attendee_product_total.amount),
                    'attendee_total': str(attendee_total.amount),
                    'currency': package_price.currency.code,
                })
            
            checkout_total = total_before_discount - total_discount
            
            return {
                'total_before_discount': str(total_before_discount.amount),
                'total_discount': str(total_discount.amount),
                'total_amount': str(checkout_total.amount),
                'currency': checkout_total.currency.code,
                'attendees': attendee_previews,
                'payment_method_type': None,  # Will be set by endpoint
                'auto_create_tickets': None,  # Will depend on payment method
            }
            
        except Exception as exc:
            logger.error(f"Checkout preview generation failed: {str(exc)}", exc_info=True)
            raise PreviewCalculationError(str(exc)) from exc
        finally:
            # Always rollback to savepoint
            transaction.savepoint_rollback(savepoint)

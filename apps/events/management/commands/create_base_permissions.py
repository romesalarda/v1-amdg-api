"""
Management command to create base event permissions.

Run with: python manage.py create_base_permissions
"""

from django.core.management.base import BaseCommand
from apps.events.models import EventPermission, EventPermissionCategoryChoices


class Command(BaseCommand):
    help = 'Creates base event permissions for all categories'

    def handle(self, *args, **options):
        permissions_to_create = [
            # GENERAL
            {
                'code': 'VIEW_EVENT_DETAILS',
                'name': 'View Event Details',
                'description': 'Can view basic event information',
                'category': EventPermissionCategoryChoices.GENERAL
            },
            {
                'code': 'MANAGE_EVENT_SETTINGS',
                'name': 'Manage Event Settings',
                'description': 'Can modify event settings and configuration',
                'category': EventPermissionCategoryChoices.GENERAL
            },
            
            # REGISTRATION
            {
                'code': 'VIEW_ATTENDEES',
                'name': 'View Attendees',
                'description': 'Can view attendee lists and information',
                'category': EventPermissionCategoryChoices.REGISTRATION
            },
            {
                'code': 'MANAGE_REGISTRATIONS',
                'name': 'Manage Registrations',
                'description': 'Can manage attendee registrations and check-ins',
                'category': EventPermissionCategoryChoices.REGISTRATION
            },
            
            # PRODUCT_MANAGEMENT
            {
                'code': 'VIEW_PRODUCTS',
                'name': 'View Products',
                'description': 'Can view event products and inventory',
                'category': EventPermissionCategoryChoices.PRODUCT_MANAGEMENT
            },
            {
                'code': 'MANAGE_PRODUCTS',
                'name': 'Manage Products',
                'description': 'Can create, update, and manage event products',
                'category': EventPermissionCategoryChoices.PRODUCT_MANAGEMENT
            },
            
            # CONTENT_MANAGEMENT
            {
                'code': 'VIEW_CONTENT',
                'name': 'View Content',
                'description': 'Can view event content and resources',
                'category': EventPermissionCategoryChoices.CONTENT_MANAGEMENT
            },
            {
                'code': 'MANAGE_CONTENT',
                'name': 'Manage Content',
                'description': 'Can create and manage event content, resources, and materials',
                'category': EventPermissionCategoryChoices.CONTENT_MANAGEMENT
            },
            
            # STAFF_MANAGEMENT
            {
                'code': 'VIEW_STAFF',
                'name': 'View Staff',
                'description': 'Can view staff members and assignments',
                'category': EventPermissionCategoryChoices.STAFF_MANAGEMENT
            },
            {
                'code': 'MANAGE_STAFF',
                'name': 'Manage Staff',
                'description': 'Can manage event staff, volunteers, and assignments',
                'category': EventPermissionCategoryChoices.STAFF_MANAGEMENT
            },
            
            # PAYMENT_MANAGEMENT
            {
                'code': 'VIEW_PAYMENTS',
                'name': 'View Payments',
                'description': 'Can view payments and payment-related records for the event',
                'category': EventPermissionCategoryChoices.PAYMENT_MANAGEMENT
            },
            {
                'code': 'MANAGE_PAYMENTS',
                'name': 'Manage Payments',
                'description': 'Can create, update, and manage payments and payment-related records',
                'category': EventPermissionCategoryChoices.PAYMENT_MANAGEMENT
            },

            # REPORTING
            {
                'code': 'VIEW_REPORTS',
                'name': 'View Reports',
                'description': 'Can view reports and analytics',
                'category': EventPermissionCategoryChoices.REPORTING
            },
            {
                'code': 'GENERATE_REPORTS',
                'name': 'Generate Reports',
                'description': 'Can generate and export reports',
                'category': EventPermissionCategoryChoices.REPORTING
            },
        ]

        created_count = 0
        skipped_count = 0

        for perm_data in permissions_to_create:
            permission, created = EventPermission.objects.get_or_create(
                code=perm_data['code'],
                defaults={
                    'name': perm_data['name'],
                    'description': perm_data['description'],
                    'category': perm_data['category']
                }
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Created permission: {permission.name} ({permission.code})')
                )
                created_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'- Skipped (already exists): {permission.name} ({permission.code})')
                )
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(f'\nSummary: Created {created_count} permissions, skipped {skipped_count} existing permissions')
        )

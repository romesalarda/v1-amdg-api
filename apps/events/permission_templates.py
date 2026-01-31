"""
Permission Templates for Event Staff Invites

This module defines predefined permission templates that can be applied when staff invites are accepted.
Templates provide a convenient way to assign common permission sets without manually selecting each permission.
"""

from apps.events.models import EventPermissionCategoryChoices

PERMISSION_TEMPLATES = {
    'REGISTRATION_MANAGER': {
        'name': 'Registration Manager',
        'description': 'Manages attendee registrations, check-ins, and attendee data',
        'permissions': [
            {
                'code': 'MANAGE_REGISTRATIONS',
                'category': EventPermissionCategoryChoices.REGISTRATION,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'VIEW_ATTENDEES',
                'category': EventPermissionCategoryChoices.REGISTRATION,
                'crud': {
                    'allow_create': False,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': True
                }
            },
        ]
    },
    'PRODUCT_MANAGER': {
        'name': 'Product Manager',
        'description': 'Manages event products, inventory, and sales',
        'permissions': [
            {
                'code': 'MANAGE_PRODUCTS',
                'category': EventPermissionCategoryChoices.PRODUCT_MANAGEMENT,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'VIEW_EVENT_DETAILS',
                'category': EventPermissionCategoryChoices.GENERAL,
                'crud': {
                    'allow_create': False,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': True
                }
            },
        ]
    },
    'CONTENT_MANAGER': {
        'name': 'Content Manager',
        'description': 'Manages event content, resources, and materials',
        'permissions': [
            {
                'code': 'MANAGE_CONTENT',
                'category': EventPermissionCategoryChoices.CONTENT_MANAGEMENT,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'VIEW_ATTENDEES',
                'category': EventPermissionCategoryChoices.REGISTRATION,
                'crud': {
                    'allow_create': False,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': True
                }
            },
        ]
    },
    'REPORTING_ANALYST': {
        'name': 'Reporting Analyst',
        'description': 'Views and generates reports and analytics',
        'permissions': [
            {
                'code': 'VIEW_REPORTS',
                'category': EventPermissionCategoryChoices.REPORTING,
                'crud': {
                    'allow_create': False,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': True
                }
            },
            {
                'code': 'GENERATE_REPORTS',
                'category': EventPermissionCategoryChoices.REPORTING,
                'crud': {
                    'allow_create': True,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': False
                }
            },
        ]
    },
    'STAFF_COORDINATOR': {
        'name': 'Staff Coordinator',
        'description': 'Manages event staff, volunteers, and assignments',
        'permissions': [
            {
                'code': 'MANAGE_STAFF',
                'category': EventPermissionCategoryChoices.STAFF_MANAGEMENT,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': False,
                    'read_only': False
                }
            },
            {
                'code': 'VIEW_EVENT_DETAILS',
                'category': EventPermissionCategoryChoices.GENERAL,
                'crud': {
                    'allow_create': False,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': True
                }
            },
        ]
    },
    'READ_ONLY_VIEWER': {
        'name': 'Read-Only Viewer',
        'description': 'View-only access to event information without modification rights',
        'permissions': [
            {
                'code': 'VIEW_EVENT_DETAILS',
                'category': EventPermissionCategoryChoices.GENERAL,
                'crud': {
                    'allow_create': False,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': True
                }
            },
            {
                'code': 'VIEW_ATTENDEES',
                'category': EventPermissionCategoryChoices.REGISTRATION,
                'crud': {
                    'allow_create': False,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': True
                }
            },
        ]
    },
    'EVENT_ADMIN': {
        'name': 'Event Administrator',
        'description': 'Full administrative access to all event functions (excluding ownership transfer)',
        'permissions': [
            {
                'code': 'MANAGE_EVENT_SETTINGS',
                'category': EventPermissionCategoryChoices.GENERAL,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'MANAGE_REGISTRATIONS',
                'category': EventPermissionCategoryChoices.REGISTRATION,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'MANAGE_PRODUCTS',
                'category': EventPermissionCategoryChoices.PRODUCT_MANAGEMENT,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'MANAGE_CONTENT',
                'category': EventPermissionCategoryChoices.CONTENT_MANAGEMENT,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'MANAGE_STAFF',
                'category': EventPermissionCategoryChoices.STAFF_MANAGEMENT,
                'crud': {
                    'allow_create': True,
                    'allow_update': True,
                    'allow_delete': True,
                    'read_only': False
                }
            },
            {
                'code': 'GENERATE_REPORTS',
                'category': EventPermissionCategoryChoices.REPORTING,
                'crud': {
                    'allow_create': True,
                    'allow_update': False,
                    'allow_delete': False,
                    'read_only': False
                }
            },
        ]
    },
}


def get_template(template_code):
    """
    Get a permission template by code.
    
    Args:
        template_code (str): The code of the template to retrieve
    
    Returns:
        dict: The template configuration or None if not found
    """
    return PERMISSION_TEMPLATES.get(template_code)


def get_all_templates():
    """
    Get all available permission templates.
    
    Returns:
        dict: Dictionary of all templates with their codes as keys
    """
    return PERMISSION_TEMPLATES


def get_template_list():
    """
    Get a list of template summaries for display purposes.
    
    Returns:
        list: List of dicts with template code, name, and description
    """
    return [
        {
            'code': code,
            'name': template['name'],
            'description': template['description'],
            'permission_count': len(template['permissions'])
        }
        for code, template in PERMISSION_TEMPLATES.items()
    ]


def is_valid_template(template_code):
    """
    Check if a template code is valid.
    
    Args:
        template_code (str): The template code to validate
    
    Returns:
        bool: True if the template exists, False otherwise
    """
    return template_code in PERMISSION_TEMPLATES
